"""Load tests for etl/load/facts.py against a disposable database.

Fixture data (source_fixtures): 3 riders, 3 customers (two share an address),
3 products, 4 orders on 2025-01-01..03 whose totals (6 / 10 / 11 / 16 units)
hit all four size bands. Rider 3 never delivers, so the snapshot has idle rows.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import rejects
from load import date as load_date
from load import dimensions as load_dims
from load import facts as load_facts
from source_fixtures import DEFAULT_ITEMS, DEFAULT_ORDERS, seed_source


def build_warehouse(dsn, **source):
    with psycopg.connect(dsn) as conn:
        seed_source(conn, **source)
    with psycopg.connect(dsn) as src, psycopg.connect(dsn) as wh:
        load_date.load_date_dimension(src, wh)
        load_dims.load_dimensions(src, wh)


def run_facts(dsn):
    with psycopg.connect(dsn) as src, psycopg.connect(dsn) as wh:
        return load_facts.load_facts(src, wh)


def fetch(dsn, sql):
    with psycopg.connect(dsn) as conn:
        return conn.execute(sql).fetchall()


def fingerprint(dsn):
    return fetch(
        dsn,
        "SELECT"
        ' (SELECT md5(string_agg(t::text, \'|\' ORDER BY "orderDeliveryKey")) FROM "FACT_ORDERDELIVERY" t),'
        ' (SELECT md5(string_agg(t::text, \'|\' ORDER BY "orderItemKey")) FROM "FACT_ORDERITEM" t),'
        ' (SELECT md5(string_agg(t::text, \'|\' ORDER BY "riderDailyKey")) FROM "FACT_RIDERDAILY" t)',
    )


def test_order_fact_has_one_row_per_order_with_resolved_keys_and_bands(test_db):
    build_warehouse(test_db)

    summary = run_facts(test_db)

    assert summary["FACT_ORDERDELIVERY"]["loaded"] == len(DEFAULT_ORDERS)
    rows = fetch(
        test_db,
        'SELECT f."orderNumber", d."fullDate"::text, r."riderId", c."customerId", g."country", '
        's."sizeName", f."orderCount", f."totalQuantity", f."lineItemCount" '
        'FROM "FACT_ORDERDELIVERY" f '
        'JOIN "DIM_DATE" d ON d."dateKey" = f."deliveryDateKey" '
        'JOIN "DIM_RIDER" r USING ("riderKey") JOIN "DIM_CUSTOMER" c USING ("customerKey") '
        'JOIN "DIM_GEOGRAPHY" g USING ("geoKey") JOIN "DIM_ORDERSIZE" s USING ("orderSizeKey") '
        'ORDER BY f."orderNumber"',
    )
    assert rows == [
        ("ORD1", "2025-01-01", 1, 1, "Philippines", "Small", 1, 6, 1),
        ("ORD2", "2025-01-02", 1, 2, "Philippines", "Medium", 1, 10, 2),  # MM/DD/YYYY source date
        ("ORD3", "2025-01-02", 2, 3, "Chile", "Large", 1, 11, 2),
        ("ORD4", "2025-01-03", 2, 1, "Philippines", "Bulk", 1, 16, 2),
    ]


def test_customers_sharing_an_address_share_a_geography_key(test_db):
    build_warehouse(test_db)
    run_facts(test_db)

    geo = dict(fetch(
        test_db,
        'SELECT f."orderNumber", f."geoKey" FROM "FACT_ORDERDELIVERY" f',
    ))
    assert geo["ORD1"] == geo["ORD2"] == geo["ORD4"] != geo["ORD3"]


def test_item_fact_copies_parent_keys_and_values_lines_at_list_price(test_db):
    build_warehouse(test_db)

    summary = run_facts(test_db)

    assert summary["FACT_ORDERITEM"]["loaded"] == len(DEFAULT_ITEMS)
    assert fetch(
        test_db,
        'SELECT i."orderNumber", p."productId", i."quantity", i."lineValue" '
        'FROM "FACT_ORDERITEM" i JOIN "DIM_PRODUCT" p USING ("productKey") '
        'ORDER BY i."orderNumber", p."productId"',
    ) == [
        ("ORD1", 1, 6, Decimal("10.62")),
        ("ORD2", 1, 5, Decimal("8.85")),
        ("ORD2", 2, 5, Decimal("16.40")),
        ("ORD3", 2, 1, Decimal("3.28")),
        ("ORD3", 3, 10, Decimal("199.90")),
        ("ORD4", 1, 10, Decimal("17.70")),
        ("ORD4", 2, 6, Decimal("19.68")),
    ]
    mismatched_parents = fetch(
        test_db,
        'SELECT count(*) FROM "FACT_ORDERITEM" i JOIN "FACT_ORDERDELIVERY" d USING ("orderNumber") '
        'WHERE (i."deliveryDateKey", i."riderKey", i."geoKey", i."orderSizeKey", i."customerKey") '
        'IS DISTINCT FROM (d."deliveryDateKey", d."riderKey", d."geoKey", d."orderSizeKey", d."customerKey")',
    )
    assert mismatched_parents == [(0,)]


def test_rider_daily_covers_every_rider_and_date_including_idle_days(test_db):
    build_warehouse(test_db)

    summary = run_facts(test_db)

    assert summary["FACT_RIDERDAILY"]["loaded"] == 3 * 3  # 3 riders x 3 dates
    assert summary["FACT_RIDERDAILY"]["idleRows"] == 5
    rows = fetch(
        test_db,
        'SELECT r."riderId", d."fullDate"::text, f."ordersDelivered", f."itemsDelivered", '
        'f."maxBasket", f."isActiveDay" FROM "FACT_RIDERDAILY" f '
        'JOIN "DIM_RIDER" r USING ("riderKey") JOIN "DIM_DATE" d ON d."dateKey" = f."dateKey" '
        'ORDER BY r."riderId", d."fullDate"',
    )
    assert rows == [
        (1, "2025-01-01", 1, 6, 6, 1),
        (1, "2025-01-02", 1, 10, 10, 1),
        (1, "2025-01-03", 0, 0, 0, 0),  # idle day: zeros, not missing
        (2, "2025-01-01", 0, 0, 0, 0),
        (2, "2025-01-02", 1, 11, 11, 1),
        (2, "2025-01-03", 1, 16, 16, 1),
        (3, "2025-01-01", 0, 0, 0, 0),
        (3, "2025-01-02", 0, 0, 0, 0),
        (3, "2025-01-03", 0, 0, 0, 0),
    ]


def test_max_basket_is_the_largest_single_order_not_the_day_total(test_db):
    orders = DEFAULT_ORDERS + [(5, "ORD5", "2025-01-01", 1, 3)]
    items = DEFAULT_ITEMS + [(5, 3, 2)]
    build_warehouse(test_db, orders=orders, items=items)

    run_facts(test_db)

    assert fetch(
        test_db,
        'SELECT f."ordersDelivered", f."itemsDelivered", f."maxBasket" FROM "FACT_RIDERDAILY" f '
        'JOIN "DIM_RIDER" r USING ("riderKey") WHERE r."riderId" = 1 AND f."dateKey" = 20250101',
    ) == [(2, 8, 6)]


def test_consistency_checks_all_pass(test_db):
    build_warehouse(test_db)

    summary = run_facts(test_db)

    assert summary["consistencyChecks"] and all(summary["consistencyChecks"].values())


def test_rerun_reproduces_identical_fact_tables(test_db):
    build_warehouse(test_db)
    run_facts(test_db)
    before = fingerprint(test_db)

    run_facts(test_db)

    assert fingerprint(test_db) == before


@pytest.mark.parametrize(
    ("orders", "items", "reason"),
    [
        (DEFAULT_ORDERS + [(5, "ORD5", "2025-01-02", 99, 1)], DEFAULT_ITEMS + [(5, 1, 1)], "rider 99 not in DIM_RIDER"),
        (DEFAULT_ORDERS + [(5, "ORD5", "2025-01-02", 1, 1)], DEFAULT_ITEMS, "order has no items"),
    ],
)
def test_an_unresolvable_order_aborts_the_load_and_is_recorded(test_db, orders, items, reason):
    build_warehouse(test_db, orders=orders, items=items)

    with pytest.raises(load_facts.RejectedRowsError, match="1 source rows could not be resolved"):
        run_facts(test_db)

    for table in ("FACT_ORDERDELIVERY", "FACT_ORDERITEM", "FACT_RIDERDAILY"):
        assert fetch(test_db, f'SELECT count(*) FROM "{table}"') == [(0,)]
    entry = json.loads(rejects.LEDGER_PATH.read_text(encoding="utf-8"))["modes"]["facts"]
    assert entry["passed"] is False and entry["rejectCount"] == 1
    assert reason in entry["rejects"][0]["reason"]


def test_a_failed_reload_keeps_the_previous_facts(test_db):
    build_warehouse(test_db)
    run_facts(test_db)
    before = fingerprint(test_db)
    with psycopg.connect(test_db) as conn:
        conn.execute(
            'INSERT INTO "Orders" ("id", "orderNumber", "deliveryDate", "deliveryRiderId", "userId", '
            "\"createdAt\", \"updatedAt\") VALUES (9, 'ORD9', 'not-a-date', 1, 1, now(), now())"
        )
        conn.execute(
            'INSERT INTO "OrderItems" ("OrderId", "ProductId", "quantity", "createdAt", "updatedAt") '
            "VALUES (9, 1, 1, now(), now())"
        )

    with pytest.raises(load_facts.RejectedRowsError):
        run_facts(test_db)

    assert fingerprint(test_db) == before


def test_foreign_keys_are_revalidated_after_the_bulk_load(test_db, monkeypatch):
    """A bad key that slips past resolution is still caught when the FKs return."""
    build_warehouse(test_db)
    run_facts(test_db)
    before = fingerprint(test_db)
    real_load_items = load_facts._load_items

    def load_items_with_a_bad_product(source_conn, wcur, maps, ledger, rejected_orders):
        source_rows, loaded = real_load_items(source_conn, wcur, maps, ledger, rejected_orders)
        wcur.execute(
            'UPDATE "FACT_ORDERITEM" SET "productKey" = 999999 '
            'WHERE "orderItemKey" = (SELECT min("orderItemKey") FROM "FACT_ORDERITEM")'
        )
        return source_rows, loaded

    monkeypatch.setattr(load_facts, "_load_items", load_items_with_a_bad_product)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        run_facts(test_db)

    assert fingerprint(test_db) == before
    assert fetch(
        test_db,
        "SELECT count(*) FROM pg_constraint c JOIN pg_class r ON r.oid = c.conrelid "
        "WHERE c.contype = 'f' AND r.relname LIKE 'FACT_%'",
    ) == [(13,)]
