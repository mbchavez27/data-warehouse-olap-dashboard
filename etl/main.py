#!/usr/bin/env python3
"""ETL entry point: readiness checks and the DIM_DATE load mode."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import preflight
import load_date


class UsageError(ValueError):
    """The CLI arguments are invalid; callers should exit with status 2."""


def usage() -> str:
    return "\n".join(
        [
            "Usage:",
            "  uv run --project etl python etl/main.py --check",
            "  uv run --project etl python etl/main.py --date",
            "",
            "--check runs the read-only readiness gate.",
            "--date replaces DIM_DATE from the parsed source delivery-date range.",
        ]
    )


def main(argv: Optional[List[str]] = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--check"]:
        report = preflight.run_preflight()
        total = sum(report["source"]["counts"].values())
        print(
            f"preflight passed: source holds {total:,} rows with exact counts; "
            "warehouse readiness passed:true"
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
