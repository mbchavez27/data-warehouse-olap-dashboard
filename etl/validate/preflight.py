"""Readiness gate: source counts exact + warehouse readiness passed.

Read-only by construction — every statement issued here is a SELECT, so
running preflight can never modify either database. Later phases call
run_preflight() before writing anything.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from core import config, db


class PreflightError(RuntimeError):
    """A named gate failed; the message says which and how to fix it."""


READINESS_SQL = (
    config.REPO_ROOT / "db" / "dw" / "validate" / "warehouse_readiness.sql"
)


def check_source(conn) -> Dict[str, Any]:
    """Assert the source holds exactly the accepted dataset row counts."""
    counts: Dict[str, int] = {}
    with conn.cursor() as cur:
        for table in config.EXPECTED_SOURCE_COUNTS:
            cur.execute(f'SELECT count(*) FROM "{table}"')
            counts[table] = cur.fetchone()[0]
    mismatches = [
        {"table": table, "expected": expected, "actual": counts[table]}
        for table, expected in config.EXPECTED_SOURCE_COUNTS.items()
        if counts[table] != expected
    ]
    return {
        "counts": counts,
        "countMismatches": mismatches,
        "passed": not mismatches,
    }


def check_warehouse(conn) -> Dict[str, Any]:
    """Run the shared readiness gate and require passed:true."""
    row = conn.execute(READINESS_SQL.read_text(encoding="utf-8")).fetchone()
    return json.loads(row[0])


def run_preflight(
    env: Optional[Dict[str, str]] = None, *, require_empty_facts: bool = True
) -> Dict[str, Any]:
    """Open both databases, run both gates, or raise naming the failure.

    ``require_empty_facts`` selects the warehouse verdict: True (the default,
    used by --check and --date) needs the pre-load state, ``passed``; False
    (used by the reloadable --dims/--facts modes) needs only
    ``structurallyReady``, which still holds after facts are loaded.
    """
    try:
        source = db.connect_source(env)
    except ConnectionError as exc:
        raise PreflightError(f"preflight: source gate failed: {exc}") from exc
    try:
        with source:
            source_report = check_source(source)
    finally:
        source.close()
    if not source_report["passed"]:
        raise PreflightError(
            "preflight: source counts mismatch: "
            f"{source_report['countMismatches']}"
        )
    try:
        warehouse = db.connect_warehouse(env)
    except ConnectionError as exc:
        raise PreflightError(f"preflight: warehouse gate failed: {exc}") from exc
    try:
        with warehouse:
            warehouse_report = check_warehouse(warehouse)
    finally:
        warehouse.close()
    verdict = "passed" if require_empty_facts else "structurallyReady"
    if (
        require_empty_facts
        and warehouse_report.get("structurallyReady") is True
        and warehouse_report.get("factRows", 0) > 0
    ):
        raise PreflightError(
            f"preflight: {warehouse_report['factRows']:,} fact rows are loaded; this mode "
            "only runs before the fact load. Reset with ./db/scripts/setup_dw.sh "
            "--schema-only, then run --date, --dims, --facts in order."
        )
    if warehouse_report.get(verdict) is not True:
        raise PreflightError(
            f"preflight: warehouse not ready ({verdict} is not true): "
            f"{warehouse_report}"
        )
    return {"passed": True, "source": source_report, "warehouse": warehouse_report}
