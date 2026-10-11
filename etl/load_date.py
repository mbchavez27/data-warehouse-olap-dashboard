"""Populate DIM_DATE from the runtime Orders.deliveryDate range."""

from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

import dates
import db
import preflight


DATE_COLUMNS = (
    "dateKey",
    "fullDate",
    "dayOfMonth",
    "dayName",
    "isWeekend",
    "isPayDay",
    "weekOfYear",
    "monthNumber",
    "monthName",
    "quarter",
    "year",
)

EXPECTED_ORDER_SIZE_SEEDS = [
    (0, "Unknown", "Unknown", 0, 0),
    (1, "Small", "Light", 1, 6),
    (2, "Medium", "Light", 7, 10),
    (3, "Large", "Heavy", 11, 15),
    (4, "Bulk", "Heavy", 16, 2147483647),
]

SOURCE_DATES_SQL = 'SELECT DISTINCT "deliveryDate" FROM "Orders"'
INSERT_DATE_SQL = """
INSERT INTO "DIM_DATE" (
  "dateKey", "fullDate", "dayOfMonth", "dayName", "isWeekend", "isPayDay",
  "weekOfYear", "monthNumber", "monthName", "quarter", "year"
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""
ORDER_SIZE_SEEDS_SQL = """
SELECT "orderSizeKey", "sizeName", "sizeGroup", "minQuantity", "maxQuantity"
FROM "DIM_ORDERSIZE"
ORDER BY "orderSizeKey"
"""


def _fetch_source_dates(source_conn) -> List[str]:
    with source_conn.cursor() as cursor:
        cursor.execute(SOURCE_DATES_SQL)
        return [row[0] for row in cursor.fetchall()]


def _as_insert_tuple(row: Dict[str, object]) -> Tuple[object, ...]:
    return tuple(row[column] for column in DATE_COLUMNS)


def _verify_order_size_seeds(cursor) -> None:
    cursor.execute(ORDER_SIZE_SEEDS_SQL)
    actual = cursor.fetchall()
    if actual != EXPECTED_ORDER_SIZE_SEEDS:
        raise RuntimeError(
            "DIM_ORDERSIZE seed verification failed: "
            f"expected {EXPECTED_ORDER_SIZE_SEEDS!r}, got {actual!r}"
        )


def load_date_dimension(source_conn, warehouse_conn) -> Dict[str, object]:
    """Replace DIM_DATE atomically and prove its count and static seeds."""
    date_rows = dates.build_date_rows(_fetch_source_dates(source_conn))
    insert_rows: Iterable[Tuple[object, ...]] = (
        _as_insert_tuple(row) for row in date_rows
    )

    with warehouse_conn.transaction():
        with warehouse_conn.cursor() as cursor:
            cursor.execute('DELETE FROM "DIM_DATE"')
            cursor.executemany(INSERT_DATE_SQL, insert_rows)
            cursor.execute('SELECT count(*) FROM "DIM_DATE"')
            inserted_count = cursor.fetchone()[0]
            if inserted_count != len(date_rows):
                raise RuntimeError(
                    "DIM_DATE row-count verification failed: "
                    f"expected {len(date_rows)}, got {inserted_count}"
                )
            _verify_order_size_seeds(cursor)

    return {
        "dateCount": len(date_rows),
        "minDate": date_rows[0]["fullDate"].isoformat(),
        "maxDate": date_rows[-1]["fullDate"].isoformat(),
        "orderSizeSeedCount": len(EXPECTED_ORDER_SIZE_SEEDS),
    }


def run_date_load() -> Dict[str, object]:
    """Run the shared read-only preflight, then perform the date load."""
    preflight.run_preflight()
    source_conn = db.connect_source()
    try:
        warehouse_conn = db.connect_warehouse()
        try:
            return load_date_dimension(source_conn, warehouse_conn)
        finally:
            warehouse_conn.close()
    finally:
        source_conn.close()
