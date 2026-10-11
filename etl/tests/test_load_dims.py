"""Load tests for etl/load_dims.py against a disposable database (conftest.test_db)."""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import load_dims
import rejects

TS = "2025-09-22 16:56:36"


def seed_source(conn, *, riders=None, products=None):
    """A small source dataset carrying every dirty variant the real one has."""
    conn.execute(
        'INSERT INTO "Couriers" ("id", "name", "createdAt", "updatedAt") VALUES '
        "(1, 'JNT', %s, %s), (2, 'LBCD', %s, %s)",
        (TS, TS, TS, TS),
    )
    riders = riders or [
        (1, "Ana", "Cruz", "Bike", 1, 18, "Female"),
        (2, "Ben", "Reyes", "Motorbike", 2, 40, "M"),
        (3, "Cara", "Lim", "Trike", 1, 60, "F"),
    ]
    conn.cursor().executemany(
        'INSERT INTO "Riders" ("id", "firstName", "lastName", "vehicleType", "courierId", '
        '"age", "gender", "createdAt", "updatedAt") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
        [r + (TS, TS) for r in riders],
    )
    users = [
        (1, "u1", "Dan", "Tan", "Manila", "Philippines", "1000", "Male"),
        (2, "u2", "Eve", "Go", "Manila", "Philippines", "1000", "female"),  # same triple as u1
        (3, "u3", "Fay", "Uy", "Manila", "Chile", "2000", "F"),  # same city, other country
    ]
    conn.cursor().executemany(
        'INSERT INTO "Users" ("id", "username", "firstName", "lastName", "city", "country", '
        '"zipCode", "gender", "createdAt", "updatedAt") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
        [u + (TS, TS) for u in users],
    )
    products = products or [
        (1, "P1", "Tasty Wooden Fish", "TOYS", 1.77046),
        (2, "P2", "Practical Silk Keyboard", "make up", 3.27517),
        (3, "P3", "Incredible Metal Shirt", "Men's Apparel", 19.99),
    ]
    conn.cursor().executemany(
        'INSERT INTO "Products" ("id", "productCode", "name", "category", "price", '
        '"createdAt", "updatedAt") VALUES (%s, %s, %s, %s, %s, %s, %s)',
        [p + (TS, TS) for p in products],
    )
    conn.commit()


def run_load(dsn):
    with psycopg.connect(dsn) as source, psycopg.connect(dsn) as warehouse:
        return load_dims.load_dimensions(source, warehouse)


def fetch(dsn, sql):
    with psycopg.connect(dsn) as conn:
        return conn.execute(sql).fetchall()


def test_loads_all_four_dimensions_with_cleaned_values(test_db):
    with psycopg.connect(test_db) as conn:
        seed_source(conn)

    summary = run_load(test_db)

    assert {t: s["tableRows"] for t, s in summary.items()} == {
        "DIM_RIDER": 3,
        "DIM_GEOGRAPHY": 2,  # u1/u2 share a triple; Manila, Chile stays separate
        "DIM_CUSTOMER": 3,
        "DIM_PRODUCT": 3,
    }
    assert fetch(
        test_db,
        'SELECT "riderId", "fullName", "vehicleType", "courierName", "ageBand", "gender" '
        'FROM "DIM_RIDER" WHERE "riderKey" <> 0 ORDER BY "riderId"',
    ) == [
        (1, "Ana Cruz", "Bicycle", "JNT", "18-29", "F"),
        (2, "Ben Reyes", "Motorcycle", "LBCD", "40-49", "M"),
        (3, "Cara Lim", "Trike", "JNT", "50-60", "F"),
    ]
    assert fetch(
        test_db,
        'SELECT "productId", "category", "listPrice" FROM "DIM_PRODUCT" '
        'WHERE "productKey" <> 0 ORDER BY "productId"',
    ) == [(1, "Toys", Decimal("1.77")), (2, "Makeup", Decimal("3.28")), (3, "Men's Apparel", Decimal("19.99"))]
    assert fetch(test_db, 'SELECT "gender" FROM "DIM_CUSTOMER" WHERE "customerKey" <> 0 ORDER BY "customerId"') == [
        ("M",),
        ("F",),
        ("F",),
    ]


def test_unknown_members_survive_the_load(test_db):
    with psycopg.connect(test_db) as conn:
        seed_source(conn)

    run_load(test_db)

    for table, key in [("DIM_RIDER", "riderKey"), ("DIM_GEOGRAPHY", "geoKey"),
                       ("DIM_CUSTOMER", "customerKey"), ("DIM_PRODUCT", "productKey")]:
        assert fetch(test_db, f'SELECT count(*) FROM "{table}" WHERE "{key}" = 0') == [(1,)]


def test_rerun_is_idempotent_and_keeps_surrogate_keys(test_db):
    with psycopg.connect(test_db) as conn:
        seed_source(conn)
    run_load(test_db)
    keys_before = fetch(test_db, 'SELECT "customerId", "customerKey" FROM "DIM_CUSTOMER" ORDER BY 1')

    second = run_load(test_db)

    assert all(s["inserted"] == 0 and s["updated"] == 0 for s in second.values())
    assert second["DIM_CUSTOMER"]["unchanged"] == 3
    assert fetch(test_db, 'SELECT "customerId", "customerKey" FROM "DIM_CUSTOMER" ORDER BY 1') == keys_before


def test_changed_source_attributes_overwrite_in_place(test_db):
    with psycopg.connect(test_db) as conn:
        seed_source(conn)
    run_load(test_db)
    key_before = fetch(test_db, 'SELECT "productKey" FROM "DIM_PRODUCT" WHERE "productId" = 1')
    with psycopg.connect(test_db) as conn:
        conn.execute("UPDATE \"Products\" SET \"category\" = 'BAG' WHERE \"id\" = 1")

    summary = run_load(test_db)

    assert summary["DIM_PRODUCT"]["updated"] == 1
    assert fetch(test_db, 'SELECT "productKey", "category" FROM "DIM_PRODUCT" WHERE "productId" = 1') == [
        (key_before[0][0], "Bags")
    ]


@pytest.mark.parametrize(
    ("riders", "reason"),
    [
        ([(1, "Ana", "Cruz", "Scooter", 1, 30, "F")], "unmapped vehicleType"),
        ([(1, "Ana", "Cruz", "Bike", 9, 30, "F")], "courier 9 not found"),
        ([(1, "Ana", "Cruz", "Bike", 1, 70, "F")], "outside the defined bands"),
    ],
)
def test_a_rejected_row_aborts_everything_and_is_recorded(test_db, riders, reason):
    with psycopg.connect(test_db) as conn:
        seed_source(conn, riders=riders)

    with pytest.raises(load_dims.RejectedRowsError, match="1 source rows failed"):
        run_load(test_db)

    for table, key in [("DIM_RIDER", "riderKey"), ("DIM_GEOGRAPHY", "geoKey"),
                       ("DIM_CUSTOMER", "customerKey"), ("DIM_PRODUCT", "productKey")]:
        assert fetch(test_db, f'SELECT count(*) FROM "{table}" WHERE "{key}" <> 0') == [(0,)]
    ledger = json.loads(rejects.LEDGER_PATH.read_text(encoding="utf-8"))
    entry = ledger["modes"]["dims"]
    assert entry["passed"] is False and entry["rejectCount"] == 1
    assert reason in entry["rejects"][0]["reason"]
    assert entry["rejects"][0]["table"] == "DIM_RIDER"


def test_a_clean_load_writes_an_empty_passing_ledger(test_db):
    with psycopg.connect(test_db) as conn:
        seed_source(conn)

    run_load(test_db)

    entry = json.loads(rejects.LEDGER_PATH.read_text(encoding="utf-8"))["modes"]["dims"]
    assert entry == {**entry, "rejectCount": 0, "rejects": [], "passed": True}
