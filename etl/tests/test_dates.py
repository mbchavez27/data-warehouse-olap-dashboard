"""Behavioral tests for the DIM_DATE ETL mode.

Database connections are lightweight in-memory fakes at the DB-API boundary;
the parser, calendar derivation, loader transaction, and CLI are real code.
"""

from __future__ import annotations

import sys
from contextlib import nullcontext
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dates
import load_date


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2025-05-24", date(2025, 5, 24)),
        ("06/25/2025", date(2025, 6, 25)),
        ("2024-02-29", date(2024, 2, 29)),
    ],
)
def test_parse_delivery_date_accepts_both_source_formats(raw, expected):
    assert dates.parse_delivery_date(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [None, "", "2025/05/24", "25/05/2025", "2025-02-29", "02/30/2025", "garbage"],
)
def test_parse_delivery_date_rejects_missing_malformed_and_impossible_values(raw):
    with pytest.raises(ValueError, match="deliveryDate"):
        dates.parse_delivery_date(raw)


@pytest.mark.parametrize(
    ("full_date", "expected"),
    [
        (
            date(2025, 2, 15),
            {
                "dateKey": 20250215,
                "fullDate": date(2025, 2, 15),
                "dayOfMonth": 15,
                "dayName": "Saturday",
                "isWeekend": True,
                "isPayDay": True,
                "weekOfYear": 7,
                "monthNumber": 2,
                "monthName": "February",
                "quarter": 1,
                "year": 2025,
            },
        ),
        (
            date(2025, 2, 28),
            {
                "dateKey": 20250228,
                "fullDate": date(2025, 2, 28),
                "dayOfMonth": 28,
                "dayName": "Friday",
                "isWeekend": False,
                "isPayDay": True,
                "weekOfYear": 9,
                "monthNumber": 2,
                "monthName": "February",
                "quarter": 1,
                "year": 2025,
            },
        ),
        (
            date(2021, 1, 1),
            {
                "dateKey": 20210101,
                "fullDate": date(2021, 1, 1),
                "dayOfMonth": 1,
                "dayName": "Friday",
                "isWeekend": False,
                "isPayDay": False,
                "weekOfYear": 1,
                "monthNumber": 1,
                "monthName": "January",
                "quarter": 1,
                "year": 2021,
            },
        ),
    ],
)
def test_derive_date_row_produces_all_eleven_attributes(full_date, expected):
    assert dates.derive_date_row(full_date) == expected


@pytest.mark.parametrize(
    ("full_date", "quarter"),
    [
        (date(2025, 3, 31), 1),
        (date(2025, 4, 1), 2),
        (date(2025, 7, 1), 3),
        (date(2025, 10, 1), 4),
    ],
)
def test_derive_date_row_handles_quarter_boundaries(full_date, quarter):
    assert dates.derive_date_row(full_date)["quarter"] == quarter


@pytest.mark.parametrize(
    ("full_date", "week", "year"),
    [
        (date(2025, 1, 1), 1, 2025),  # Jan 1 always opens week 1
        (date(2025, 1, 7), 1, 2025),
        (date(2025, 1, 8), 2, 2025),
        (date(2024, 12, 29), 52, 2024),  # leap year: day 364 closes week 52
        (date(2024, 12, 30), 53, 2024),  # 2-day week 53 stays in its own year
        (date(2024, 12, 31), 53, 2024),
        (date(2025, 12, 31), 53, 2025),  # non-leap: day 365 is a 1-day week 53
    ],
)
def test_derive_date_row_uses_calendar_weeks_that_never_cross_a_year(full_date, week, year):
    row = dates.derive_date_row(full_date)
    assert (row["weekOfYear"], row["year"]) == (week, year)


@pytest.mark.parametrize(
    ("full_date", "is_weekend"),
    [
        (date(2025, 2, 14), False),  # Friday
        (date(2025, 2, 15), True),  # Saturday
        (date(2025, 2, 16), True),  # Sunday
        (date(2025, 2, 17), False),  # Monday
    ],
)
def test_derive_date_row_flags_saturday_and_sunday_as_weekend(full_date, is_weekend):
    assert dates.derive_date_row(full_date)["isWeekend"] is is_weekend


@pytest.mark.parametrize(
    ("full_date", "is_pay_day"),
    [
        (date(2024, 2, 28), False),  # leap year: 28th is not month-end
        (date(2024, 2, 29), True),  # leap-year month-end
        (date(2025, 2, 28), True),  # non-leap month-end
        (date(2025, 4, 30), True),  # 30-day month-end
        (date(2025, 1, 31), True),  # 31-day month-end
        (date(2025, 1, 30), False),
        (date(2025, 1, 15), True),
        (date(2025, 1, 16), False),
    ],
)
def test_derive_date_row_pay_day_tracks_the_real_month_end(full_date, is_pay_day):
    assert dates.derive_date_row(full_date)["isPayDay"] is is_pay_day


def test_build_date_rows_parses_before_finding_range_and_fills_zero_order_days():
    rows = dates.build_date_rows(["2025-09-23", "09/24/2024", "2025-05-24"])

    assert len(rows) == 365
    assert rows[0]["fullDate"] == date(2024, 9, 24)
    assert rows[-1]["fullDate"] == date(2025, 9, 23)
    assert rows[1]["fullDate"] == date(2024, 9, 25)
    assert rows[100]["fullDate"] == date(2025, 1, 2)


def test_build_date_rows_rejects_an_empty_source_range():
    with pytest.raises(ValueError, match="no deliveryDate"):
        dates.build_date_rows([])


EXPECTED_ORDER_SIZE_SEEDS = [
    (0, "Unknown", "Unknown", 0, 0),
    (1, "Small", "Light", 1, 6),
    (2, "Medium", "Light", 7, 10),
    (3, "Large", "Heavy", 11, 15),
    (4, "Bulk", "Heavy", 16, 2147483647),
]


class SourceCursor:
    def __init__(self, values):
        self.values = values
        self.statement = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement):
        self.statement = statement

    def fetchall(self):
        return [(value,) for value in self.values]


class SourceConnection:
    def __init__(self, values):
        self.cursor_instance = SourceCursor(values)

    def cursor(self):
        return self.cursor_instance


class WarehouseCursor:
    def __init__(self, connection):
        self.connection = connection
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement):
        normalized = " ".join(statement.split())
        if normalized.startswith('DELETE FROM "DIM_DATE"'):
            self.connection.date_rows = []
        elif 'FROM "DIM_ORDERSIZE"' in normalized:
            self.result = list(self.connection.order_size_seeds)
        elif 'count(*) FROM "DIM_DATE"' in normalized:
            self.result = [(len(self.connection.date_rows),)]
        else:
            raise AssertionError(f"unexpected SQL: {normalized}")

    def executemany(self, statement, rows):
        assert 'INSERT INTO "DIM_DATE"' in statement
        self.connection.date_rows.extend(list(rows))

    def fetchall(self):
        return self.result

    def fetchone(self):
        return self.result[0]


class WarehouseConnection:
    def __init__(self):
        self.date_rows = []
        self.order_size_seeds = list(EXPECTED_ORDER_SIZE_SEEDS)
        self.transactions = 0

    def transaction(self):
        self.transactions += 1
        return nullcontext()

    def cursor(self):
        return WarehouseCursor(self)


def test_load_date_dimension_is_transactional_idempotent_and_preserves_static_seeds():
    source = SourceConnection(["09/24/2024", "2025-09-23"])
    warehouse = WarehouseConnection()

    first = load_date.load_date_dimension(source, warehouse)
    first_rows = list(warehouse.date_rows)
    second = load_date.load_date_dimension(source, warehouse)

    assert first == {
        "dateCount": 365,
        "minDate": "2024-09-24",
        "maxDate": "2025-09-23",
        "orderSizeSeedCount": 5,
    }
    assert second == first
    assert warehouse.date_rows == first_rows
    assert warehouse.transactions == 2
    assert warehouse.order_size_seeds == EXPECTED_ORDER_SIZE_SEEDS
    assert "SELECT DISTINCT" in source.cursor_instance.statement


def test_load_date_dimension_aborts_if_static_seeds_are_not_exact():
    source = SourceConnection(["2025-01-01"])
    warehouse = WarehouseConnection()
    warehouse.order_size_seeds.pop()

    with pytest.raises(RuntimeError, match="DIM_ORDERSIZE"):
        load_date.load_date_dimension(source, warehouse)


def test_run_date_load_calls_preflight_before_opening_write_connections(monkeypatch):
    module = load_date
    events = []

    def fail_preflight():
        events.append("preflight")
        raise RuntimeError("stop before connections")

    monkeypatch.setattr(module.preflight, "run_preflight", fail_preflight)
    monkeypatch.setattr(
        module.db,
        "connect_source",
        lambda: events.append("source") or pytest.fail("source opened before preflight"),
    )

    with pytest.raises(RuntimeError, match="stop before connections"):
        module.run_date_load()

    assert events == ["preflight"]


def test_main_date_mode_invokes_loader_and_keeps_check_mode(monkeypatch, capsys):
    import main as main_module

    calls = []
    monkeypatch.setattr(
        main_module.load_date,
        "run_date_load",
        lambda: calls.append("date")
        or {
            "dateCount": 365,
            "minDate": "2024-09-24",
            "maxDate": "2025-09-23",
            "orderSizeSeedCount": 5,
        },
    )
    monkeypatch.setattr(
        main_module.preflight,
        "run_preflight",
        lambda **_: {
            "source": {"counts": {"Orders": 1000000}},
            "warehouse": {"passed": True},
        },
    )

    main_module.main(["--date"])
    main_module.main(["--check"])

    assert calls == ["date"]
    output = capsys.readouterr().out
    assert "loaded DIM_DATE: 365 rows" in output
    assert "preflight passed" in output


def test_cli_exit_codes_distinguish_usage_errors_from_runtime_failures(monkeypatch, capsys):
    import main as main_module

    assert main_module.run_cli(["--bogus"]) == 2
    assert "Usage:" in capsys.readouterr().err

    monkeypatch.setattr(
        main_module.load_date,
        "run_date_load",
        lambda: (_ for _ in ()).throw(RuntimeError("warehouse unavailable")),
    )
    assert main_module.run_cli(["--date"]) == 1
    assert "ERROR: warehouse unavailable" in capsys.readouterr().err
