"""Load the three fact tables: order delivery, order item, rider daily.

Orders and order items stream from source_db through server-side cursors.
Each row's natural references (delivery date, rider, customer, the customer's
address, product) are resolved to warehouse surrogate keys through in-memory
maps built from the loaded dimensions, then bulk-copied into the facts.
FACT_RIDERDAILY is derived inside the warehouse from FACT_ORDERDELIVERY
(rider x date, zero-order days included), so the snapshot cannot disagree
with the order fact it summarizes.

All three tables reload in one transaction: they are truncated, refilled, and
cross-checked before commit. Any unresolvable row aborts the whole load and is
listed in evidence/etl-rejects.json; nothing is mapped to Unknown silently.
"""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import dates
import db
import preflight
import rejects
import transform

ITERSIZE = 10_000

DELIVERY_SQL = """
SELECT o."id", o."orderNumber", o."deliveryDate", o."deliveryRiderId", o."userId",
       coalesce(i.units, 0), coalesce(i.lines, 0)
FROM "Orders" o
LEFT JOIN (
  SELECT "OrderId", sum("quantity") AS units, count(*) AS lines
  FROM "OrderItems" GROUP BY "OrderId"
) i ON i."OrderId" = o."id"
ORDER BY o."id"
"""

ITEM_SQL = """
SELECT oi."OrderId", oi."ProductId", oi."quantity",
       o."orderNumber", o."deliveryDate", o."deliveryRiderId", o."userId",
       sum(oi."quantity") OVER (PARTITION BY oi."OrderId") AS units
FROM "OrderItems" oi JOIN "Orders" o ON o."id" = oi."OrderId"
ORDER BY oi."OrderId", oi."ProductId"
"""

CUSTOMER_ADDRESS_SQL = 'SELECT "id", "country", "city", "zipCode" FROM "Users"'

DELIVERY_COLUMNS = (
    "orderNumber", "deliveryDateKey", "riderKey", "geoKey", "orderSizeKey",
    "customerKey", "orderCount", "totalQuantity", "lineItemCount",
)
ITEM_COLUMNS = (
    "orderNumber", "deliveryDateKey", "riderKey", "geoKey", "orderSizeKey",
    "customerKey", "productKey", "quantity", "lineValue",
)

RIDERDAILY_SQL = """
INSERT INTO "FACT_RIDERDAILY"
  ("dateKey", "riderKey", "ordersDelivered", "itemsDelivered", "maxBasket", "isActiveDay")
SELECT d."dateKey", r."riderKey",
       coalesce(a.orders, 0), coalesce(a.units, 0), coalesce(a.max_basket, 0),
       CASE WHEN a.orders IS NULL THEN 0 ELSE 1 END
FROM "DIM_RIDER" r
CROSS JOIN "DIM_DATE" d
LEFT JOIN (
  SELECT "riderKey", "deliveryDateKey",
         count(*) AS orders, sum("totalQuantity") AS units, max("totalQuantity") AS max_basket
  FROM "FACT_ORDERDELIVERY"
  GROUP BY "riderKey", "deliveryDateKey"
) a ON a."riderKey" = r."riderKey" AND a."deliveryDateKey" = d."dateKey"
WHERE r."riderKey" <> 0
ORDER BY d."dateKey", r."riderKey"
"""

# Internal consistency checks run before commit; each must return 0.
CONSISTENCY_SQL = {
    "riderDailyOrdersMatchDeliveries": (
        'SELECT (SELECT coalesce(sum("ordersDelivered"), 0) FROM "FACT_RIDERDAILY")'
        ' - (SELECT count(*) FROM "FACT_ORDERDELIVERY")'
    ),
    "riderDailyUnitsMatchDeliveries": (
        'SELECT (SELECT coalesce(sum("itemsDelivered"), 0) FROM "FACT_RIDERDAILY")'
        ' - (SELECT coalesce(sum("totalQuantity"), 0) FROM "FACT_ORDERDELIVERY")'
    ),
    "itemUnitsMatchDeliveries": (
        'SELECT (SELECT coalesce(sum("quantity"), 0) FROM "FACT_ORDERITEM")'
        ' - (SELECT coalesce(sum("totalQuantity"), 0) FROM "FACT_ORDERDELIVERY")'
    ),
    "itemRowsMatchLineItemCount": (
        'SELECT (SELECT count(*) FROM "FACT_ORDERITEM")'
        ' - (SELECT coalesce(sum("lineItemCount"), 0) FROM "FACT_ORDERDELIVERY")'
    ),
    "lineValueIsQuantityTimesListPrice": (
        'SELECT count(*) FROM "FACT_ORDERITEM" f JOIN "DIM_PRODUCT" p USING ("productKey")'
        ' WHERE f."lineValue" <> f."quantity" * p."listPrice"'
    ),
}


class RejectedRowsError(RuntimeError):
    """Source rows could not be resolved; nothing was committed."""


class KeyMaps:
    """Natural reference -> warehouse surrogate key, built from loaded dimensions."""

    def __init__(self, warehouse_conn, source_conn) -> None:
        with warehouse_conn.cursor() as cur:
            cur.execute('SELECT "fullDate", "dateKey" FROM "DIM_DATE"')
            self.date_keys: Dict[date, int] = dict(cur.fetchall())
            cur.execute('SELECT "riderId", "riderKey" FROM "DIM_RIDER" WHERE "riderKey" <> 0')
            self.riders: Dict[int, int] = dict(cur.fetchall())
            cur.execute('SELECT "customerId", "customerKey" FROM "DIM_CUSTOMER" WHERE "customerKey" <> 0')
            self.customers: Dict[int, int] = dict(cur.fetchall())
            cur.execute(
                'SELECT "productId", "productKey", "listPrice" FROM "DIM_PRODUCT" WHERE "productKey" <> 0'
            )
            self.products: Dict[int, Tuple[int, Decimal]] = {
                pid: (key, price) for pid, key, price in cur.fetchall()
            }
            cur.execute('SELECT "country", "city", "zipCode", "geoKey" FROM "DIM_GEOGRAPHY" WHERE "geoKey" <> 0')
            geo_keys = {(c, ci, z): key for c, ci, z, key in cur.fetchall()}
            cur.execute(
                'SELECT "orderSizeKey", "minQuantity", "maxQuantity" FROM "DIM_ORDERSIZE" ORDER BY 1'
            )
            self.bands: List[Tuple[int, int, int]] = cur.fetchall()
        # Customer -> geoKey through the customer's address (decision D12).
        self.customer_geo: Dict[int, int] = {}
        with source_conn.cursor(name="src_customer_address") as scur:
            scur.itersize = ITERSIZE
            scur.execute(CUSTOMER_ADDRESS_SQL)
            for user_id, country, city, zip_code in scur:
                key = geo_keys.get(tuple((v or "").strip() for v in (country, city, zip_code)))
                if key is not None:
                    self.customer_geo[user_id] = key
        self._parsed_dates: Dict[Any, int] = {}

    def date_key(self, raw: Any) -> int:
        cached = self._parsed_dates.get(raw)
        if cached is not None:
            return cached
        parsed = dates.parse_delivery_date(raw)
        key = self.date_keys.get(parsed)
        if key is None:
            raise ValueError(f"deliveryDate {raw!r} has no DIM_DATE row (run --date)")
        self._parsed_dates[raw] = key
        return key

    def order(self, number: Any, raw_date: Any, rider_id: Any, user_id: Any, units: Any) -> Tuple[Any, ...]:
        """Resolve one order's references: the five parent-order columns."""
        if not isinstance(number, str) or not number.strip():
            raise ValueError(f"orderNumber is missing or blank: {number!r}")
        rider_key = self.riders.get(rider_id)
        if rider_key is None:
            raise ValueError(f"rider {rider_id!r} not in DIM_RIDER")
        customer_key = self.customers.get(user_id)
        if customer_key is None:
            raise ValueError(f"customer {user_id!r} not in DIM_CUSTOMER")
        geo_key = self.customer_geo.get(user_id)
        if geo_key is None:
            raise ValueError(f"customer {user_id!r} address not in DIM_GEOGRAPHY")
        if not units:
            raise ValueError("order has no items")
        size_key = transform.size_band_key(int(units), self.bands)
        return (number.strip(), self.date_key(raw_date), rider_key, geo_key, size_key, customer_key)


FACT_TABLES = ("FACT_ORDERDELIVERY", "FACT_ORDERITEM", "FACT_RIDERDAILY")


def _truncate_facts(wcur) -> None:
    wcur.execute(
        'TRUNCATE "FACT_RIDERDAILY", "FACT_ORDERITEM", "FACT_ORDERDELIVERY" RESTART IDENTITY'
    )


def _suspend_fact_fks(wcur) -> List[Tuple[str, str, str]]:
    """Drop the fact tables' FKs for the bulk load; return their definitions.

    Checking 3M rows one at a time is the slowest part of the load. Re-adding
    the constraints afterwards (_restore_fact_fks) validates every row in one
    set-based pass instead. Both happen inside the load transaction, so a
    failed validation rolls back the rows and the dropped constraints together.
    """
    wcur.execute(
        "SELECT r.relname, c.conname, pg_get_constraintdef(c.oid) "
        "FROM pg_constraint c JOIN pg_class r ON r.oid = c.conrelid "
        "JOIN pg_namespace n ON n.oid = r.relnamespace "
        "WHERE c.contype = 'f' AND n.nspname = current_schema() AND r.relname = ANY(%s) "
        "ORDER BY r.relname, c.conname",
        (list(FACT_TABLES),),
    )
    constraints = wcur.fetchall()
    for table, name, _definition in constraints:
        wcur.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT "{name}"')
    return constraints


def _restore_fact_fks(wcur, constraints: List[Tuple[str, str, str]]) -> None:
    for table, name, definition in constraints:
        wcur.execute(f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" {definition}')


def _quoted(names: Sequence[str]) -> str:
    return ", ".join(f'"{name}"' for name in names)


def _load_deliveries(source_conn, wcur, maps: KeyMaps, ledger: rejects.Ledger) -> Tuple[int, int, Set[int]]:
    rejected_orders: Set[int] = set()
    source_rows = 0
    loaded = 0
    with source_conn.cursor(name="src_orders") as scur:
        scur.itersize = ITERSIZE
        scur.execute(DELIVERY_SQL)
        with wcur.copy(f'COPY "FACT_ORDERDELIVERY" ({_quoted(DELIVERY_COLUMNS)}) FROM STDIN') as copy:
            for order_id, number, raw_date, rider_id, user_id, units, lines in scur:
                source_rows += 1
                try:
                    parent = maps.order(number, raw_date, rider_id, user_id, units)
                except ValueError as error:
                    ledger.add("FACT_ORDERDELIVERY", order_id, str(error))
                    rejected_orders.add(order_id)
                    continue
                copy.write_row(parent + (1, int(units), int(lines)))
                loaded += 1
    return source_rows, loaded, rejected_orders


def _load_items(source_conn, wcur, maps: KeyMaps, ledger: rejects.Ledger, rejected_orders: Set[int]) -> Tuple[int, int]:
    source_rows = 0
    loaded = 0
    current_order: Optional[int] = None
    parent: Optional[Tuple[Any, ...]] = None
    with source_conn.cursor(name="src_order_items") as scur:
        scur.itersize = ITERSIZE
        scur.execute(ITEM_SQL)
        with wcur.copy(f'COPY "FACT_ORDERITEM" ({_quoted(ITEM_COLUMNS)}) FROM STDIN') as copy:
            for order_id, product_id, quantity, number, raw_date, rider_id, user_id, units in scur:
                source_rows += 1
                if order_id in rejected_orders:
                    continue  # already recorded once at order level
                if order_id != current_order:
                    current_order = order_id
                    parent = maps.order(number, raw_date, rider_id, user_id, units)
                product = maps.products.get(product_id)
                if product is None:
                    ledger.add("FACT_ORDERITEM", f"{order_id}|{product_id}", f"product {product_id!r} not in DIM_PRODUCT")
                    continue
                if not isinstance(quantity, int) or quantity <= 0:
                    ledger.add("FACT_ORDERITEM", f"{order_id}|{product_id}", f"quantity must be a positive integer: {quantity!r}")
                    continue
                product_key, list_price = product
                copy.write_row(parent + (product_key, quantity, quantity * list_price))
                loaded += 1
    return source_rows, loaded


def _count(wcur, table: str) -> int:
    wcur.execute(f'SELECT count(*) FROM "{table}"')
    return wcur.fetchone()[0]


def load_facts(source_conn, warehouse_conn) -> Dict[str, Any]:
    """Reload all three facts atomically; return per-table counts and checks."""
    ledger = rejects.Ledger()
    summary: Dict[str, Any] = {}
    try:
        with warehouse_conn.transaction():
            with warehouse_conn.cursor() as wcur:
                started = time.perf_counter()
                maps = KeyMaps(warehouse_conn, source_conn)
                summary["keyMapsSeconds"] = round(time.perf_counter() - started, 3)
                _truncate_facts(wcur)
                suspended = _suspend_fact_fks(wcur)

                started = time.perf_counter()
                source_orders, delivered, rejected_orders = _load_deliveries(source_conn, wcur, maps, ledger)
                summary["FACT_ORDERDELIVERY"] = {
                    "sourceRows": source_orders,
                    "loaded": delivered,
                    "seconds": round(time.perf_counter() - started, 3),
                }
                if ledger.count:
                    raise RejectedRowsError(_reject_message(ledger))

                started = time.perf_counter()
                source_items, items = _load_items(source_conn, wcur, maps, ledger, rejected_orders)
                summary["FACT_ORDERITEM"] = {
                    "sourceRows": source_items,
                    "loaded": items,
                    "seconds": round(time.perf_counter() - started, 3),
                }
                if ledger.count:
                    raise RejectedRowsError(_reject_message(ledger))

                started = time.perf_counter()
                wcur.execute(RIDERDAILY_SQL)
                expected_snapshot = len(maps.riders) * len(maps.date_keys)
                summary["FACT_RIDERDAILY"] = {
                    "expectedRows": expected_snapshot,
                    "loaded": _count(wcur, "FACT_RIDERDAILY"),
                    "seconds": round(time.perf_counter() - started, 3),
                }
                wcur.execute('SELECT count(*) FROM "FACT_RIDERDAILY" WHERE "isActiveDay" = 0')
                summary["FACT_RIDERDAILY"]["idleRows"] = wcur.fetchone()[0]

                started = time.perf_counter()
                _restore_fact_fks(wcur, suspended)
                summary["foreignKeys"] = {
                    "revalidated": len(suspended),
                    "seconds": round(time.perf_counter() - started, 3),
                }
                _verify(wcur, summary, source_orders, source_items, expected_snapshot)
    finally:
        rejects.write("facts", ledger)
    return summary


def _reject_message(ledger: rejects.Ledger) -> str:
    return (
        f"{ledger.count} source rows could not be resolved; nothing was loaded "
        f"(see {rejects.LEDGER_PATH.name}): {ledger.by_reason()}"
    )


def _verify(wcur, summary: Dict[str, Any], source_orders: int, source_items: int, snapshot: int) -> None:
    """Abort before commit if any count or consistency check fails."""
    failures = []
    for table, expected in (
        ("FACT_ORDERDELIVERY", source_orders),
        ("FACT_ORDERITEM", source_items),
        ("FACT_RIDERDAILY", snapshot),
    ):
        actual = _count(wcur, table)
        if actual != expected:
            failures.append(f"{table} has {actual} rows; expected {expected}")
    checks = {}
    for name, sql in CONSISTENCY_SQL.items():
        wcur.execute(sql)
        difference = wcur.fetchone()[0]
        checks[name] = difference == 0
        if difference != 0:
            failures.append(f"{name} is off by {difference}")
    summary["consistencyChecks"] = checks
    if failures:
        raise RuntimeError("fact load verification failed; nothing was committed: " + "; ".join(failures))


def run_facts_load() -> Dict[str, Any]:
    """Gate on the structural preflight, then reload the facts."""
    preflight.run_preflight(require_empty_facts=False)
    source_conn = db.connect_source()
    try:
        warehouse_conn = db.connect_warehouse()
        try:
            return load_facts(source_conn, warehouse_conn)
        finally:
            warehouse_conn.close()
    finally:
        source_conn.close()
