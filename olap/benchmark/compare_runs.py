#!/usr/bin/env python3
"""Compare benchmark labels: median ms, speedup vs the first label, result md5 match.

Usage:
  uv run --project etl python olap/benchmark/compare_runs.py baseline-r2 indexes config optimized
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parents[2] / "evidence" / "benchmark"


def load(label: str) -> dict:
    report = json.loads((EVIDENCE / label / "results.json").read_text(encoding="utf-8"))
    return {case["caseId"]: case for case in report["cases"]}


def main(labels: list[str]) -> int:
    if len(labels) < 2:
        raise SystemExit("usage: compare_runs.py <base-label> <label> [<label> ...]")
    runs = {label: load(label) for label in labels}
    base = runs[labels[0]]
    print(f"{'case':<26}" + "".join(f"{label:>22}" for label in labels) + "  md5")
    mismatches = 0
    for case_id, ref in base.items():
        cells = []
        for label in labels:
            ms = runs[label][case_id]["medianMs"]
            cells.append(f"{ms:9.1f} ms {ref['medianMs'] / ms:5.2f}x")
        md5_ok = all(runs[label][case_id]["resultMd5"] == ref["resultMd5"] for label in labels)
        mismatches += not md5_ok
        print(f"{case_id:<26}" + "".join(f"{c:>22}" for c in cells) + f"  {'ok' if md5_ok else 'MISMATCH'}")
    print(f"\nmd5 mismatches: {mismatches}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
