"""Read-only post-load source-to-warehouse reconciliation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import preflight
from core import config, db
from transform import dates


DEFAULT_OUTPUT = config.REPO_ROOT / "evidence" / "etl-reconciliation.json"
DEFAULT_REJECT_LEDGER = config.REPO_ROOT / "evidence" / "etl-rejects.json"

EXPECTED_UNKNOWN_SEEDS = {
    "DIM_RIDER": 1,
    "DIM_GEOGRAPHY": 1,
    "DIM_ORDERSIZE": 1,
    "DIM_CUSTOMER": 1,
    "DIM_PRODUCT": 1,
}
EXPECTED_UNKNOWN_REFERENCES = {name: 0 for name in EXPECTED_UNKNOWN_SEEDS}


class ReconciliationError(RuntimeError):
    """One or more named source-to-warehouse checks failed."""


def _check(expected: Any, actual: Any) -> Dict[str, Any]:
    return {"expected": expected, "actual": actual, "passed": actual == expected}


def _reject_count(reject_ledger: Dict[str, Any]) -> int:
    modes = reject_ledger.get("modes")
    if not isinstance(modes, dict):
        raise ValueError("reject ledger must contain a modes object")
    counts = [mode.get("rejectCount") for mode in modes.values()]
    if any(not isinstance(count, int) or count < 0 for count in counts):
        raise ValueError("every reject-ledger mode must have a nonnegative rejectCount")
    return sum(counts)


def build_report(
    source: Dict[str, Any],
    warehouse: Dict[str, Any],
    reject_ledger: Dict[str, Any],
    *,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build deterministic per-check verdicts from collected snapshots."""
    checks = {
        "factOrderDeliveryCount": _check(
            source["orders"], warehouse["factOrderDelivery"]
        ),
        "factOrderItemCount": _check(source["orderItems"], warehouse["factOrderItem"]),
        "factRiderDailyCount": _check(
            source["riders"] * source["dateCount"], warehouse["factRiderDaily"]
        ),
        "dimDateCount": _check(source["dateCount"], warehouse["dimDate"]),
        "dimRiderCount": _check(source["riders"], warehouse["dimRider"]),
        "dimGeographyCount": _check(
            source["distinctGeographies"], warehouse["dimGeography"]
        ),
        "dimCustomerCount": _check(source["users"], warehouse["dimCustomer"]),
        "dimProductCount": _check(source["products"], warehouse["dimProduct"]),
        "dimOrderSizeCount": _check(5, warehouse["dimOrderSize"]),
        "factOrderDeliveryUnits": _check(
            source["units"], warehouse["factOrderDeliveryUnits"]
        ),
        "factOrderItemUnits": _check(
            source["units"], warehouse["factOrderItemUnits"]
        ),
        "factRiderDailyUnits": _check(
            source["units"], warehouse["factRiderDailyUnits"]
        ),
        "unknownSeedRows": _check(
            EXPECTED_UNKNOWN_SEEDS, warehouse["unknownSeedRows"]
        ),
        "unknownFactReferences": _check(
            EXPECTED_UNKNOWN_REFERENCES, warehouse["unknownFactReferences"]
        ),
        "rejectCount": _check(0, _reject_count(reject_ledger)),
    }
    failed = [name for name, result in checks.items() if not result["passed"]]
    timestamp = generated_at or datetime.now(timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")
    return {
        "schemaVersion": 1,
        "generatedAt": timestamp,
        "command": "reconcile",
        "source": source,
        "warehouse": warehouse,
        "rejects": reject_ledger,
        "checks": checks,
        "failedChecks": failed,
        "passed": not failed,
    }


def read_reject_ledger(path: Optional[Path] = None) -> Dict[str, Any]:
    """Read and minimally validate the ETL reject ledger."""
    ledger_path = DEFAULT_REJECT_LEDGER if path is None else Path(path)
    report = json.loads(ledger_path.read_text(encoding="utf-8"))
    _reject_count(report)
    return report


def write_evidence(report: Dict[str, Any], output_path: Path) -> None:
    """Write a complete JSON report, creating its parent directory if needed."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def assert_reconciled(report: Dict[str, Any]) -> None:
    """Raise a named failure when any reconciliation check is false."""
    if not report["passed"]:
        raise ReconciliationError(
            "reconciliation failed: " + ", ".join(report["failedChecks"])
        )


def _collect_live_snapshots(
    env: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Collect source and warehouse totals using SELECT statements only."""
    source_conn = db.connect_source(env)
    try:
        warehouse_conn = db.connect_warehouse(env)
        try:
            with source_conn.cursor() as cursor:
                cursor.execute(
                    """
SELECT
  (SELECT count(*) FROM "Orders"),
  (SELECT count(*) FROM "OrderItems"),
  (SELECT count(*) FROM "Riders"),
  (SELECT count(*) FROM "Users"),
  (SELECT count(*) FROM "Products"),
  (SELECT count(DISTINCT (country, city, "zipCode")) FROM "Users"),
  (SELECT coalesce(sum(quantity), 0) FROM "OrderItems")
"""
                )
                source_values = cursor.fetchone()
                cursor.execute('SELECT DISTINCT "deliveryDate" FROM "Orders"')
                raw_dates = [row[0] for row in cursor.fetchall()]

            source_names = (
                "orders",
                "orderItems",
                "riders",
                "users",
                "products",
                "distinctGeographies",
                "units",
            )
            source = dict(zip(source_names, source_values))
            source["dateCount"] = len(dates.build_date_rows(raw_dates))

            with warehouse_conn.cursor() as cursor:
                cursor.execute(
                    """
SELECT
  (SELECT count(*) FROM "FACT_ORDERDELIVERY"),
  (SELECT count(*) FROM "FACT_ORDERITEM"),
  (SELECT count(*) FROM "FACT_RIDERDAILY"),
  (SELECT count(*) FROM "DIM_DATE"),
  (SELECT count(*) FROM "DIM_RIDER" WHERE "riderKey" <> 0),
  (SELECT count(*) FROM "DIM_GEOGRAPHY" WHERE "geoKey" <> 0),
  (SELECT count(*) FROM "DIM_CUSTOMER" WHERE "customerKey" <> 0),
  (SELECT count(*) FROM "DIM_PRODUCT" WHERE "productKey" <> 0),
  (SELECT count(*) FROM "DIM_ORDERSIZE"),
  (SELECT coalesce(sum("totalQuantity"), 0) FROM "FACT_ORDERDELIVERY"),
  (SELECT coalesce(sum("quantity"), 0) FROM "FACT_ORDERITEM"),
  (SELECT coalesce(sum("itemsDelivered"), 0) FROM "FACT_RIDERDAILY")
"""
                )
                warehouse_values = cursor.fetchone()
                cursor.execute(
                    """
SELECT
  (SELECT count(*) FROM "DIM_RIDER" WHERE "riderKey" = 0),
  (SELECT count(*) FROM "DIM_GEOGRAPHY" WHERE "geoKey" = 0),
  (SELECT count(*) FROM "DIM_ORDERSIZE" WHERE "orderSizeKey" = 0),
  (SELECT count(*) FROM "DIM_CUSTOMER" WHERE "customerKey" = 0),
  (SELECT count(*) FROM "DIM_PRODUCT" WHERE "productKey" = 0)
"""
                )
                unknown_seed_values = cursor.fetchone()
                cursor.execute(
                    """
SELECT
  (SELECT count(*) FROM "FACT_ORDERDELIVERY" WHERE "riderKey" = 0)
    + (SELECT count(*) FROM "FACT_RIDERDAILY" WHERE "riderKey" = 0),
  (SELECT count(*) FROM "FACT_ORDERDELIVERY" WHERE "geoKey" = 0),
  (SELECT count(*) FROM "FACT_ORDERDELIVERY" WHERE "orderSizeKey" = 0)
    + (SELECT count(*) FROM "FACT_ORDERITEM" WHERE "orderSizeKey" = 0),
  (SELECT count(*) FROM "FACT_ORDERDELIVERY" WHERE "customerKey" = 0),
  (SELECT count(*) FROM "FACT_ORDERITEM" WHERE "productKey" = 0)
"""
                )
                unknown_reference_values = cursor.fetchone()

            warehouse_names = (
                "factOrderDelivery",
                "factOrderItem",
                "factRiderDaily",
                "dimDate",
                "dimRider",
                "dimGeography",
                "dimCustomer",
                "dimProduct",
                "dimOrderSize",
                "factOrderDeliveryUnits",
                "factOrderItemUnits",
                "factRiderDailyUnits",
            )
            unknown_names = tuple(EXPECTED_UNKNOWN_SEEDS)
            warehouse = dict(zip(warehouse_names, warehouse_values))
            warehouse["unknownSeedRows"] = dict(
                zip(unknown_names, unknown_seed_values)
            )
            warehouse["unknownFactReferences"] = dict(
                zip(unknown_names, unknown_reference_values)
            )
            return source, warehouse
        finally:
            warehouse_conn.close()
    finally:
        source_conn.close()


def run_reconciliation(
    output_path: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
    *,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Preflight, collect read-only snapshots, write evidence, and assert it."""
    preflight.run_preflight(env=env, require_empty_facts=False)
    source, warehouse = _collect_live_snapshots(env)
    report = build_report(
        source,
        warehouse,
        read_reject_ledger(),
        generated_at=generated_at,
    )
    write_evidence(report, DEFAULT_OUTPUT if output_path is None else Path(output_path))
    assert_reconciled(report)
    return report
