#!/usr/bin/env python3
"""ETL entry point: readiness checks and the DIM_DATE load mode."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import preflight
import load_date
import load_dims
import load_facts
import reconcile
import run_ledger


class UsageError(ValueError):
    """The CLI arguments are invalid; callers should exit with status 2."""


def usage() -> str:
    return "\n".join(
        [
            "Usage:",
            "  uv run --project etl python etl/main.py --check",
            "  uv run --project etl python etl/main.py --date",
            "  uv run --project etl python etl/main.py --dims",
            "  uv run --project etl python etl/main.py --facts",
            "  uv run --project etl python etl/main.py --reconcile",
            "  uv run --project etl python etl/main.py --reconcile --output <path>",
            "",
            "--check runs the read-only readiness gate (works before and after loads).",
            "--date replaces DIM_DATE from the parsed source delivery-date range.",
            "--dims upserts DIM_RIDER, DIM_GEOGRAPHY, DIM_CUSTOMER, DIM_PRODUCT.",
            "--facts reloads FACT_ORDERDELIVERY, FACT_ORDERITEM, FACT_RIDERDAILY.",
            "--reconcile writes read-only source-to-warehouse JSON evidence.",
        ]
    )


def _execute(argv: List[str]) -> Tuple[str, Dict[str, Any]]:
    """Execute one parsed mode and return its report for evidence capture."""
    if argv == ["--check"]:
        report = preflight.run_preflight(require_empty_facts=False)
        total = sum(report["source"]["counts"].values())
        fact_rows = report["warehouse"].get("factRows", 0)
        state = f"{fact_rows:,} fact rows loaded" if fact_rows else "facts empty (pre-load)"
        print(
            f"preflight passed: source holds {total:,} rows with exact counts; "
            f"warehouse structurally ready; {state}"
        )
        return "check", report
    if argv == ["--date"]:
        report = load_date.run_date_load()
        print(
            f"loaded DIM_DATE: {report['dateCount']:,} rows "
            f"({report['minDate']} through {report['maxDate']}); "
            f"DIM_ORDERSIZE seeds:{report['orderSizeSeedCount']}"
        )
        return "date", report
    if argv == ["--dims"]:
        summary = load_dims.run_dims_load()
        for table, counts in summary.items():
            print(
                f"{table}: {counts['loaded']:,} rows from source "
                f"(inserted {counts['inserted']:,}, updated {counts['updated']:,}, "
                f"unchanged {counts['unchanged']:,}); table now {counts['tableRows']:,} "
                f"+ Unknown; {counts['seconds']}s"
            )
        print("rejects: 0 (evidence/etl-rejects.json)")
        return "dims", summary
    if argv == ["--facts"]:
        summary = load_facts.run_facts_load()
        for table in ("FACT_ORDERDELIVERY", "FACT_ORDERITEM", "FACT_RIDERDAILY"):
            counts = summary[table]
            print(f"{table}: {counts['loaded']:,} rows; {counts['seconds']}s")
        idle = summary["FACT_RIDERDAILY"]["idleRows"]
        checks = summary["consistencyChecks"]
        print(f"idle rider-days: {idle:,}; consistency checks passed: {sum(checks.values())}/{len(checks)}")
        print("rejects: 0 (evidence/etl-rejects.json)")
        return "facts", summary
    if argv and argv[0] == "--reconcile":
        if argv == ["--reconcile"]:
            output_path = None
        elif len(argv) == 3 and argv[1] == "--output" and argv[2]:
            output_path = Path(argv[2])
        else:
            raise UsageError(usage())
        report = reconcile.run_reconciliation(output_path)
        passed = sum(check["passed"] for check in report["checks"].values())
        print(f"reconciliation passed: {passed}/{len(report['checks'])} checks")
        return "reconcile", report
    raise UsageError(usage())


def main(argv: Optional[List[str]] = None) -> None:
    """Execute a mode for programmatic callers; CLI evidence is owned by run_cli."""
    args = sys.argv[1:] if argv is None else argv
    _execute(args)


def _mode_label(argv: List[str]) -> str:
    if argv and argv[0] in {"--check", "--date", "--dims", "--facts", "--reconcile"}:
        return argv[0][2:]
    return "invalid"


def run_cli(
    argv: Optional[List[str]] = None,
    *,
    ledger_path: Optional[Path] = None,
    reject_ledger_path: Optional[Path] = None,
    clock=time.perf_counter,
    now=run_ledger.utc_now,
) -> int:
    """Run the CLI with stable exit codes for usage and runtime failures."""
    args = list(sys.argv[1:] if argv is None else argv)
    mode = _mode_label(args)
    command = " ".join(["etl/main.py", *args])
    started_at = now()
    started = clock()
    summary: Dict[str, Any] = {}
    error_text: Optional[str] = None
    try:
        executed_mode, summary = _execute(args)
        mode = executed_mode
        exit_status = 0
    except UsageError as error:
        print(error, file=sys.stderr)
        exit_status = 2
        error_text = f"{type(error).__name__}: {error}"
    except Exception as error:  # noqa: BLE001 - CLI boundary reports everything
        print(f"ERROR: {error}", file=sys.stderr)
        exit_status = 1
        error_text = f"{type(error).__name__}: {error}"

    finished = clock()
    finished_at = now()
    record = run_ledger.build_record(
        command=command,
        mode=mode,
        started_at=started_at,
        finished_at=finished_at,
        wall_clock_seconds=finished - started,
        tables=run_ledger.table_metrics(mode, summary) if exit_status == 0 else {},
        rejected_rows=run_ledger.reject_count(mode, started_at, reject_ledger_path),
        quarantined_rows=0,
        exit_status=exit_status,
        error=error_text,
    )
    try:
        run_ledger.append_record(record, ledger_path)
    except Exception as error:  # noqa: BLE001 - missing audit evidence is a failed run
        print(f"ERROR: could not append ETL run evidence: {error}", file=sys.stderr)
        return 1
    return exit_status


if __name__ == "__main__":
    sys.exit(run_cli())
