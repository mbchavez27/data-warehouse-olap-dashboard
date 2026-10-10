#!/usr/bin/env python3
"""ETL entry point. Phase 1 ships --check only; later phases add modes."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import preflight


def usage() -> str:
    return "\n".join(
        [
            "Usage:",
            "  uv run --project etl python etl/main.py --check",
            "",
            "Phase 1: readiness gate only (no data movement).",
        ]
    )


def main(argv: Optional[List[str]] = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv != ["--check"]:
        raise ValueError(usage())
    report = preflight.run_preflight()
    total = sum(report["source"]["counts"].values())
    print(
        f"preflight passed: source holds {total:,} rows with exact counts; "
        "warehouse readiness passed:true"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - CLI boundary reports everything
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
