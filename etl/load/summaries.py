"""Build the summary views the report queries read.

Since the Phase 2 optimization, the report SQL in olap/queries reads four
materialized views (AGG_*) instead of scanning the fact tables. The views only
exist once db/dw/optimize/ has been applied, and they hold a copy of the facts:
a rebuilt warehouse has none (the schema drops its tables with CASCADE) and a
reloaded one has stale ones. So the pipeline runs this after every load.

The SQL files in db/dw/optimize/ stay the single source of the views. This runs
them over the ETL's own warehouse connection, so it works wherever the ETL does,
a hosted database included, not only in the local container that
db/scripts/apply_optimizations.sh targets. All three files run in one
transaction and the views are checked against the facts before it commits, so a
failure leaves the previous state in place rather than half-built views.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict

from core import config, db

OPTIMIZE_DIR = config.REPO_ROOT / "db" / "dw" / "optimize"
OPTIMIZE_FILES = ("01_indexes.sql", "02_config.sql", "03_preagg.sql")
SUMMARY_VIEWS = ("AGG_CUSTOMER_PERIOD", "AGG_RIDER_DAY", "AGG_CATEGORY_PERIOD", "AGG_PRODUCT_PERIOD")

# Each view must reproduce the fact totals exactly (the same sanity check
# 03_preagg.sql prints, made fail-fast).
VERIFY_SQL = """
SELECT
  (SELECT sum(orders) FROM "AGG_RIDER_DAY") = (SELECT count(*) FROM "FACT_ORDERDELIVERY") AS rider_day_orders,
  (SELECT sum(value) FROM "AGG_CUSTOMER_PERIOD") = (SELECT sum("lineValue") FROM "FACT_ORDERITEM") AS customer_value,
  (SELECT sum(orders) FROM "AGG_CUSTOMER_PERIOD") = (SELECT count(DISTINCT "orderNumber") FROM "FACT_ORDERITEM") AS customer_orders,
  (SELECT sum(value) FROM "AGG_CATEGORY_PERIOD") = (SELECT sum("lineValue") FROM "FACT_ORDERITEM") AS category_value,
  (SELECT sum(value) FROM "AGG_PRODUCT_PERIOD") = (SELECT sum("lineValue") FROM "FACT_ORDERITEM") AS product_value,
  (SELECT sum(units) FROM "AGG_PRODUCT_PERIOD") = (SELECT sum(quantity) FROM "FACT_ORDERITEM") AS product_units
"""


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def prepare(sql: str, database: str) -> str:
    """Make a psql script runnable over psycopg.

    Drops psql meta-commands (``\\timing on``), which the server would reject,
    and points 02_config.sql's ``ALTER DATABASE dw_db`` at the database actually
    connected to, so a host with another DW_DB name gets the settings too.
    """
    kept = [line for line in sql.splitlines() if not line.lstrip().startswith("\\")]
    return "\n".join(kept).replace("ALTER DATABASE dw_db ", f"ALTER DATABASE {quote_identifier(database)} ")


def verify(cur) -> Dict[str, bool]:
    """Return each view-versus-facts check; raise if any fails."""
    cur.execute(VERIFY_SQL)
    names = [column.name for column in cur.description]
    checks = dict(zip(names, (bool(value) for value in cur.fetchone())))
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f"summary views do not match the facts: {', '.join(failed)}")
    return checks


def run_summary_build(
    connect: Callable = db.connect_warehouse,
    read_sql: Callable[[str], str] = lambda name: (OPTIMIZE_DIR / name).read_text(encoding="utf-8"),
) -> Dict[str, Any]:
    """Apply db/dw/optimize/ to the warehouse in one transaction and verify it."""
    started = time.perf_counter()
    with connect() as conn:  # commits on a clean exit, rolls back on an error
        database = conn.info.dbname
        with conn.cursor() as cur:
            for name in OPTIMIZE_FILES:
                cur.execute(prepare(read_sql(name), database))
            checks = verify(cur)
            views: Dict[str, int] = {}
            for view in SUMMARY_VIEWS:
                cur.execute(f"SELECT count(*) FROM {quote_identifier(view)}")
                views[view] = cur.fetchone()[0]
    return {"views": views, "checks": checks, "seconds": round(time.perf_counter() - started, 1)}

