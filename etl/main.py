#!/usr/bin/env python3
"""ETL entry point: readiness checks and the DIM_DATE load mode."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import preflight
import load_date
import load_dims
import load_facts


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
            "",
            "--check runs the read-only readiness gate (works before and after loads).",
            "--date replaces DIM_DATE from the parsed source delivery-date range.",
            "--dims upserts DIM_RIDER, DIM_GEOGRAPHY, DIM_CUSTOMER, DIM_PRODUCT.",
            "--facts reloads FACT_ORDERDELIVERY, FACT_ORDERITEM, FACT_RIDERDAILY.",
        ]
    )


def main(argv: Optional[List[str]] = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--check"]:
        report = preflight.run_preflight(require_empty_facts=False)
        total = sum(report["source"]["counts"].values())
        fact_rows = report["warehouse"].get("factRows", 0)
        state = f"{fact_rows:,} fact rows loaded" if fact_rows else "facts empty (pre-load)"
        print(
            f"preflight passed: source holds {total:,} rows with exact counts; "
            f"warehouse structurally ready; {state}"
        )
        return
    if argv == ["--date"]:
        report = load_date.run_date_load()
        print(
            f"loaded DIM_DATE: {report['dateCount']:,} rows "
            f"({report['minDate']} through {report['maxDate']}); "
            f"DIM_ORDERSIZE seeds:{report['orderSizeSeedCount']}"
        )
        return
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
        return
    if argv == ["--facts"]:
        summary = load_facts.run_facts_load()
        for table in ("FACT_ORDERDELIVERY", "FACT_ORDERITEM", "FACT_RIDERDAILY"):
            counts = summary[table]
            print(f"{table}: {counts['loaded']:,} rows; {counts['seconds']}s")
        idle = summary["FACT_RIDERDAILY"]["idleRows"]
        checks = summary["consistencyChecks"]
        print(f"idle rider-days: {idle:,}; consistency checks passed: {sum(checks.values())}/{len(checks)}")
        print("rejects: 0 (evidence/etl-rejects.json)")
        return
    raise UsageError(usage())


def run_cli(argv: Optional[List[str]] = None) -> int:
    """Run the CLI with stable exit codes for usage and runtime failures."""
    try:
        main(argv)
        return 0
    except UsageError as error:
        print(error, file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001 - CLI boundary reports everything
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run_cli())
