#!/usr/bin/env python3
"""Time every OLAP report case and save the results as evidence.

For each case: one discarded warm-up run, then N measured runs (default 5)
timed on the client around execute + fetch. Then one EXPLAIN (ANALYZE,
BUFFERS) run captures the plan and server-side execution time. The session
is read-only, so the benchmark can never change the warehouse.

Outputs (under evidence/benchmark/<label>/):
  results.json    environment, warehouse state, per-case timings and stats
  results.csv     one row per case, for the report's tables and charts
  plans/<case>.txt  EXPLAIN (ANALYZE, BUFFERS) output per case

Usage:
  uv run --project etl python olap/benchmark/run_benchmark.py --label baseline
  uv run --project etl python olap/benchmark/run_benchmark.py --label optimized --runs 5
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "etl"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import psycopg  # noqa: E402

from core import config  # noqa: E402

from cases import CASES  # noqa: E402

QUERIES_DIR = REPO_ROOT / "olap" / "queries"
EVIDENCE_DIR = REPO_ROOT / "evidence" / "benchmark"
PARAM = re.compile(r":'([a-z_]+)'")


def to_driver_sql(sql_text: str, params: Dict[str, str]) -> tuple[str, Dict[str, str]]:
    """Turn psql-style :'name' parameters into psycopg %(name)s placeholders.

    Every parameter the file uses gets a value; missing ones are '' (= all),
    which is exactly what the API will send.
    """
    names = sorted(set(PARAM.findall(sql_text)))
    unknown = set(params) - set(names)
    if unknown:
        raise ValueError(f"unknown parameters {sorted(unknown)}")
    bound = {name: params.get(name, "") for name in names}
    # Escape literal % (e.g. in LIKE) before adding placeholders.
    text = sql_text.replace("%", "%%")
    text = PARAM.sub(lambda m: f"%({m.group(1)})s::text", text)
    # Drop the trailing semicolon so the statement can be wrapped in EXPLAIN.
    return text.strip().rstrip(";"), bound


def environment(conn) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SELECT version()")
        version = cur.fetchone()[0]
        settings = {}
        for name in ("shared_buffers", "work_mem", "effective_cache_size",
                     "max_parallel_workers_per_gather", "jit"):
            cur.execute(f"SHOW {name}")
            settings[name] = cur.fetchone()[0]
        cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
        db_size = cur.fetchone()[0]
        cur.execute(
            "SELECT relname, n_live_tup FROM pg_stat_user_tables "
            "WHERE relname LIKE 'FACT_%' OR relname LIKE 'DIM_%' ORDER BY relname"
        )
        table_rows = {name: count for name, count in cur.fetchall()}
        cur.execute(
            "SELECT tablename, indexname FROM pg_indexes "
            "WHERE schemaname = current_schema() ORDER BY 1, 2"
        )
        indexes = [f"{t}.{i}" for t, i in cur.fetchall()]
    return {
        "postgres": version,
        "settings": settings,
        "databaseSize": db_size,
        "tableRowEstimates": table_rows,
        "indexes": indexes,
        "client": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
    }


def connect(plan_cache_mode: str):
    """Fresh read-only session with an explicit plan-cache mode.

    psycopg prepares a statement on the server after 5 executions; PostgreSQL
    may then switch to a generic plan built without the parameter values.
    With the "(:'x' = '' OR column = :'x')" filter pattern that plan cannot
    see which filters are empty and badly underestimates rows (measured: an
    estimate of 1 row for 1,000,000, so a nested loop with 364M comparisons,
    ~27 s instead of ~0.25 s). Pinning the mode makes every run comparable:
      force_custom_plan   planned with the actual values each time (default)
      force_generic_plan  the plan a long-lived server gets after warm-up
    """
    conn = psycopg.connect(config.dw_dsn(), autocommit=True)
    conn.execute("SET default_transaction_read_only = on")
    conn.execute(f"SET plan_cache_mode = {plan_cache_mode}")
    return conn


def run_case(conn, case, runs: int, plans_dir: Path, queries_dir: Path) -> Dict[str, Any]:
    sql_text = (queries_dir / case.query_file).read_text(encoding="utf-8")
    statement, bound = to_driver_sql(sql_text, case.params)
    timings: List[float] = []
    rows = columns = 0
    result_md5 = ""
    with conn.cursor() as cur:
        for attempt in range(runs + 1):  # attempt 0 is the warm-up
            started = time.perf_counter()
            cur.execute(statement, bound)
            result = cur.fetchall()
            elapsed_ms = (time.perf_counter() - started) * 1000
            if attempt == 0:
                rows, columns = len(result), len(cur.description)
                # repr, not json: lineValue is numeric (Decimal), which json cannot encode.
                result_md5 = hashlib.md5(repr(result).encode("utf-8")).hexdigest()
                continue
            timings.append(round(elapsed_ms, 2))
        cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) " + statement, bound)
        plan_lines = [line[0] for line in cur.fetchall()]
    plan_text = "\n".join(plan_lines)
    (plans_dir / f"{case.case_id}.txt").write_text(
        f"-- {case.case_id}: {case.note}\n-- file: olap/queries/{case.query_file}\n"
        f"-- params: {json.dumps(case.params)}\n\n{plan_text}\n",
        encoding="utf-8",
    )
    exec_ms = re.search(r"Execution Time: ([\d.]+) ms", plan_text)
    plan_ms = re.search(r"Planning Time: ([\d.]+) ms", plan_text)
    return {
        "caseId": case.case_id,
        "report": case.report,
        "queryFile": f"olap/queries/{case.query_file}",
        "params": case.params,
        "note": case.note,
        "resultRows": rows,
        "resultColumns": columns,
        "resultMd5": result_md5,
        "runsMs": timings,
        "medianMs": round(statistics.median(timings), 2),
        "meanMs": round(statistics.mean(timings), 2),
        "minMs": min(timings),
        "maxMs": max(timings),
        "stdevMs": round(statistics.stdev(timings), 2) if len(timings) > 1 else 0.0,
        "explainExecutionMs": float(exec_ms.group(1)) if exec_ms else None,
        "explainPlanningMs": float(plan_ms.group(1)) if plan_ms else None,
        "planFile": f"plans/{case.case_id}.txt",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True, help="e.g. baseline, optimized")
    parser.add_argument("--runs", type=int, default=5, help="measured runs per case (default 5)")
    parser.add_argument("--only", help="run only case ids containing this text")
    parser.add_argument("--queries-dir", default=str(QUERIES_DIR),
                        help="query tree with the same relative paths")
    parser.add_argument(
        "--plan-cache-mode",
        choices=("force_custom_plan", "force_generic_plan"),
        default="force_custom_plan",
        help="PostgreSQL plan_cache_mode for every run (see connect())",
    )
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[a-z0-9-]+", args.label):
        parser.error("--label may contain only lowercase letters, digits and '-'")
    if args.runs < 2:
        parser.error("--runs must be at least 2")

    out_dir = EVIDENCE_DIR / args.label
    plans_dir = out_dir / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    cases = [c for c in CASES if not args.only or args.only in c.case_id]

    probe = connect(args.plan_cache_mode)
    try:
        env = environment(probe)
    finally:
        probe.close()
    started_at = datetime.now(timezone.utc)
    results = []
    for case in cases:
        print(f"{case.case_id:<26}", end="", flush=True)
        conn = connect(args.plan_cache_mode)  # fresh session: no plan carried between cases
        try:
            result = run_case(conn, case, args.runs, plans_dir, Path(args.queries_dir))
        finally:
            conn.close()
        results.append(result)
        print(f"median {result['medianMs']:>9.1f} ms  "
              f"(min {result['minMs']:.1f}, max {result['maxMs']:.1f}, "
              f"sd {result['stdevMs']:.1f})  rows {result['resultRows']}")
    finished_at = datetime.now(timezone.utc)

    report = {
        "schemaVersion": 1,
        "label": args.label,
        "startedAt": started_at.isoformat(timespec="seconds"),
        "finishedAt": finished_at.isoformat(timespec="seconds"),
        "method": {
            "warmupRuns": 1,
            "measuredRuns": args.runs,
            "timing": "client wall-clock around execute + fetchall, read-only session",
            "plans": "one EXPLAIN (ANALYZE, BUFFERS) run after the timed runs",
            "planCacheMode": args.plan_cache_mode,
            "session": "fresh connection per case",
            "queriesDir": args.queries_dir,
        },
        "environment": env,
        "cases": results,
    }
    (out_dir / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    with (out_dir / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["case_id", "report", "query_file", "params", "result_rows",
                         "result_columns", "result_md5", "median_ms", "mean_ms", "min_ms", "max_ms",
                         "stdev_ms", "explain_execution_ms"])
        for r in results:
            writer.writerow([r["caseId"], r["report"], r["queryFile"], json.dumps(r["params"]),
                             r["resultRows"], r["resultColumns"], r["resultMd5"], r["medianMs"], r["meanMs"],
                             r["minMs"], r["maxMs"], r["stdevMs"], r["explainExecutionMs"]])
    print(f"\nwrote {out_dir.relative_to(REPO_ROOT)}/results.json, results.csv, plans/ "
          f"({len(results)} cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
