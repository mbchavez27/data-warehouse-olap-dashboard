#!/usr/bin/env python3
"""Capture the plan PostgreSQL really uses for a prepared report statement.

run_benchmark.py saves EXPLAIN (ANALYZE) on the statement with its values
bound, and the planner then plans for those values, so the saved plan never
shows what a generic plan does. This script prepares the statement and runs
EXPLAIN (ANALYZE, BUFFERS) EXECUTE under each plan_cache_mode, so a generic
plan is a generic plan.

The session is read-only. Output: one text file per case and mode under
the --out directory, plus summary.json.

Usage:
  uv run --project etl python olap/benchmark/capture_generic_plan.py \
      --out evidence/warehouse-verification/generic-plans-before-analyze --cases R4-trend-month R4-busiest-days
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "etl"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402

from core import config  # noqa: E402

from cases import CASES  # noqa: E402

QUERIES_DIR = REPO_ROOT / "olap" / "queries"
PARAM = re.compile(r":'([a-z_]+)'")
MODES = ("force_custom_plan", "force_generic_plan")


def prepared_sql(sql_text: str, params: dict) -> tuple[str, list[str]]:
    """psql-style :'name' -> numbered $n::text parameters, one per distinct name."""
    names = sorted(set(PARAM.findall(sql_text)))
    unknown = set(params) - set(names)
    if unknown:
        raise ValueError(f"unknown parameters {sorted(unknown)}")
    index = {name: i + 1 for i, name in enumerate(names)}
    text = sql_text.replace("%", "%%")
    text = PARAM.sub(lambda m: f"${index[m.group(1)]}::text", text)
    return text.strip().rstrip(";"), names


def prepared_exists(conn) -> bool:
    return conn.execute("SELECT 1 FROM pg_prepared_statements WHERE name = 'q'").fetchone() is not None


def capture(conn, case, mode: str, out_dir: Path) -> dict:
    text, names = prepared_sql((QUERIES_DIR / case.query_file).read_text(encoding="utf-8"), case.params)
    values = [case.params.get(name, "") for name in names]
    conn.execute(f"SET plan_cache_mode = {mode}")
    conn.execute("DEALLOCATE q") if prepared_exists(conn) else None
    conn.execute(f"PREPARE q({', '.join(['text'] * len(names))}) AS {text}")
    execute = sql.SQL("EXECUTE q({})").format(sql.SQL(", ").join(sql.Literal(v) for v in values))
    explain = sql.SQL("EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) ") + execute
    with conn.cursor() as cur:
        cur.execute(explain)
        plan = "\n".join(row[0] for row in cur.fetchall())
    conn.execute("DEALLOCATE q")
    (out_dir / f"{case.case_id}.{mode}.txt").write_text(
        f"-- {case.case_id} under {mode}\n-- file: olap/queries/{case.query_file}\n"
        f"-- params: {json.dumps(case.params)}\n\n{plan}\n",
        encoding="utf-8",
    )
    exec_ms = re.search(r"Execution Time: ([\d.]+) ms", plan)
    plan_ms = re.search(r"Planning Time: ([\d.]+) ms", plan)
    return {
        "caseId": case.case_id,
        "planCacheMode": mode,
        "executionMs": float(exec_ms.group(1)) if exec_ms else None,
        "planningMs": float(plan_ms.group(1)) if plan_ms else None,
        "nestedLoop": "Nested Loop" in plan,
        "hashJoin": "Hash Join" in plan or "Hash Right Join" in plan or "Hash Left Join" in plan,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="directory to write plans into")
    parser.add_argument("--cases", nargs="+", required=True, help="case ids from cases.py")
    parser.add_argument("--timeout-s", type=int, default=180)
    args = parser.parse_args()

    wanted = {case.case_id: case for case in CASES}
    missing = [c for c in args.cases if c not in wanted]
    if missing:
        raise SystemExit(f"unknown cases: {missing}")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = psycopg.connect(config.dw_dsn(), autocommit=True)
    conn.prepare_threshold = None  # no driver-side auto-prepare; only our explicit PREPARE
    conn.execute("SET default_transaction_read_only = on")
    conn.execute(f"SET statement_timeout = {args.timeout_s * 1000}")
    summary = []
    for case_id in args.cases:
        for mode in MODES:
            row = capture(conn, wanted[case_id], mode, out_dir)
            summary.append(row)
            print(f"{case_id:18} {mode:19} exec {row['executionMs']:>10.1f} ms  "
                  f"plan {row['planningMs']:.1f} ms  nestedLoop={row['nestedLoop']}")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
