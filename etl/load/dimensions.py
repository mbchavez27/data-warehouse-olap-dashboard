"""Load the four source-driven dimensions: rider, geography, customer, product.

Each dimension streams from source_db through a server-side cursor, is
cleaned row by row (`etl/transform/values.py`), bulk-copied into a temporary staging
table, and upserted into the warehouse by its natural key, so surrogate keys
stay stable across reruns (SCD Type 1: changed attributes are overwritten).
All four run in one warehouse transaction. Any rejected row aborts the whole
load before anything is committed; the rejects are written to
evidence/etl-rejects.json either way.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Sequence, Tuple

from core import db, rejects
from extract import queries
from transform import values
from validate import preflight

ITERSIZE = 10_000


class RejectedRowsError(RuntimeError):
    """Source rows failed cleaning; nothing was committed."""


def _text(value: Any, column: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{column} is missing or blank: {value!r}")
    return value.strip()


def _rider(row: Sequence[Any]) -> Tuple[Any, ...]:
    rider_id, first, last, vehicle, courier_id, courier_name, age, gender = row
    if courier_name is None:
        raise ValueError(f"courier {courier_id!r} not found in Couriers")
    return (
        rider_id,
        values.full_name(first, last),
        values.normalize_vehicle(vehicle),
        courier_id,
        _text(courier_name, "courierName"),
        age,
        values.rider_age_band(age),
        values.normalize_gender(gender),
    )


def _geography(row: Sequence[Any]) -> Tuple[Any, ...]:
    country, city, zip_code = row
    return (_text(country, "country"), _text(city, "city"), _text(zip_code, "zipCode"))


def _customer(row: Sequence[Any]) -> Tuple[Any, ...]:
    customer_id, username, first, last, gender = row
    return (
        customer_id,
        _text(username, "username"),
        first,
        last,
        None if gender is None else values.normalize_gender(gender),
    )


def _product(row: Sequence[Any]) -> Tuple[Any, ...]:
    product_id, code, name, category, price_text = row
    return (
        product_id,
        _text(code, "productCode"),
        _text(name, "productName"),
        values.normalize_category(category),
        values.to_list_price(price_text),
    )


@dataclass(frozen=True)
class Dimension:
    table: str
    source_sql: str
    clean: Callable[[Sequence[Any]], Tuple[Any, ...]]
    columns: Tuple[str, ...]  # warehouse columns, in clean() order
    stage_types: Tuple[str, ...]
    natural_key: Tuple[str, ...]
    surrogate_key: str

    def source_id(self, row: Sequence[Any]) -> Any:
        """Identifier shown in reject records."""
        return "|".join(map(str, row[: len(self.natural_key)]))


DIMENSIONS: Tuple[Dimension, ...] = (
    Dimension(
        table="DIM_RIDER",
        source_sql=queries.RIDER_SOURCE_SQL,
        clean=_rider,
        columns=("riderId", "fullName", "vehicleType", "courierId", "courierName", "age", "ageBand", "gender"),
        stage_types=("integer", "text", "text", "integer", "text", "integer", "text", "text"),
        natural_key=("riderId",),
        surrogate_key="riderKey",
    ),
    Dimension(
        table="DIM_GEOGRAPHY",
        source_sql=queries.GEOGRAPHY_SOURCE_SQL,
        clean=_geography,
        columns=("country", "city", "zipCode"),
        stage_types=("text", "text", "text"),
        natural_key=("country", "city", "zipCode"),
        surrogate_key="geoKey",
    ),
    Dimension(
        table="DIM_CUSTOMER",
        source_sql=queries.CUSTOMER_SOURCE_SQL,
        clean=_customer,
        columns=("customerId", "username", "firstName", "lastName", "gender"),
        stage_types=("integer", "text", "text", "text", "text"),
        natural_key=("customerId",),
        surrogate_key="customerKey",
    ),
    Dimension(
        table="DIM_PRODUCT",
        source_sql=queries.PRODUCT_SOURCE_SQL,
        clean=_product,
        columns=("productId", "productCode", "productName", "category", "listPrice"),
        stage_types=("integer", "text", "text", "text", "numeric(12,2)"),
        natural_key=("productId",),
        surrogate_key="productKey",
    ),
)


def _quoted(names: Sequence[str]) -> str:
    return ", ".join(f'"{name}"' for name in names)


def _upsert_sql(dim: Dimension, stage: str) -> str:
    cols = _quoted(dim.columns)
    attributes = [c for c in dim.columns if c not in dim.natural_key]
    if attributes:
        sets = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in attributes)
        target = ", ".join(f't."{c}"' for c in attributes)
        excluded = ", ".join(f'EXCLUDED."{c}"' for c in attributes)
        action = f"DO UPDATE SET {sets} WHERE ({target}) IS DISTINCT FROM ({excluded})"
    else:
        action = "DO NOTHING"
    return (
        f'INSERT INTO "{dim.table}" AS t ({cols}) SELECT {cols} FROM {stage} '
        f"ON CONFLICT ({_quoted(dim.natural_key)}) {action} "
        "RETURNING (xmax = 0) AS inserted"
    )


def _stage_dimension(dim: Dimension, source_conn, wcur, ledger: rejects.Ledger) -> Tuple[str, int, int]:
    """Stream, clean, and COPY one dimension into a temp table."""
    stage = f"stage_{dim.table.lower()}"
    column_defs = ", ".join(f'"{c}" {t}' for c, t in zip(dim.columns, dim.stage_types))
    wcur.execute(f"CREATE TEMP TABLE {stage} ({column_defs}) ON COMMIT DROP")
    source_rows = 0
    staged = 0
    with source_conn.cursor(name=f"src_{dim.table.lower()}") as scur:
        scur.itersize = ITERSIZE
        scur.execute(dim.source_sql)
        with wcur.copy(f"COPY {stage} ({_quoted(dim.columns)}) FROM STDIN") as copy:
            for row in scur:
                source_rows += 1
                try:
                    cleaned = dim.clean(row)
                except ValueError as error:
                    ledger.add(dim.table, dim.source_id(row), str(error))
                    continue
                copy.write_row(cleaned)
                staged += 1
    return stage, source_rows, staged


def _check_unique(dim: Dimension, stage: str, wcur) -> None:
    key = _quoted(dim.natural_key)
    wcur.execute(f"SELECT count(*) - count(DISTINCT ({key})) FROM {stage}")
    duplicates = wcur.fetchone()[0]
    if duplicates:
        raise RejectedRowsError(f"{dim.table}: {duplicates} duplicate natural keys in source")


def load_dimensions(source_conn, warehouse_conn) -> Dict[str, Dict[str, Any]]:
    """Stage and upsert all four dimensions atomically; return per-table counts."""
    ledger = rejects.Ledger()
    summary: Dict[str, Dict[str, Any]] = {}
    try:
        with warehouse_conn.transaction():
            with warehouse_conn.cursor() as wcur:
                staged: List[Tuple[Dimension, str, int, int, float]] = []
                for dim in DIMENSIONS:
                    started = time.perf_counter()
                    stage, source_rows, kept = _stage_dimension(dim, source_conn, wcur, ledger)
                    staged.append((dim, stage, source_rows, kept, time.perf_counter() - started))
                if ledger.count:
                    raise RejectedRowsError(
                        f"{ledger.count} source rows failed cleaning; nothing was loaded "
                        f"(see {rejects.LEDGER_PATH.name}): {ledger.by_reason()}"
                    )
                for dim, stage, source_rows, kept, stage_seconds in staged:
                    started = time.perf_counter()
                    _check_unique(dim, stage, wcur)
                    wcur.execute(_upsert_sql(dim, stage))
                    results = [row[0] for row in wcur.fetchall()]
                    inserted = sum(1 for flag in results if flag)
                    updated = len(results) - inserted
                    wcur.execute(f'SELECT count(*) FROM "{dim.table}" WHERE "{dim.surrogate_key}" <> 0')
                    summary[dim.table] = {
                        "sourceRows": source_rows,
                        "loaded": kept,
                        "inserted": inserted,
                        "updated": updated,
                        "unchanged": kept - inserted - updated,
                        "tableRows": wcur.fetchone()[0],
                        "seconds": round(stage_seconds + time.perf_counter() - started, 3),
                    }
    finally:
        rejects.write("dims", ledger)
    return summary


def run_dims_load() -> Dict[str, Dict[str, Any]]:
    """Gate on the structural preflight, then load the dimensions."""
    preflight.run_preflight(require_empty_facts=False)
    source_conn = db.connect_source()
    try:
        warehouse_conn = db.connect_warehouse()
        try:
            return load_dimensions(source_conn, warehouse_conn)
        finally:
            warehouse_conn.close()
    finally:
        source_conn.close()
