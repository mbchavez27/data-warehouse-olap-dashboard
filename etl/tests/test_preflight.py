"""Tests for etl/preflight.py and etl/main.py guards.

All connections are fakes: nothing here touches a database. The recorded
statements double as the read-only proof (every issued statement is SELECT).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db as db_module
import preflight
from preflight import PreflightError, check_source, run_preflight


class FakeCursor:
    def __init__(self, script, log):
        self._script = script
        self._log = log
        self._row = (0,)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._log.append(sql)
        for marker, row in self._script.items():
            if marker in sql:
                self._row = row
                return
        self._row = (0,)

    def fetchone(self):
        return self._row


class FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class FakeConn:
    """Minimal psycopg stand-in: cursor() context managers + direct execute."""

    def __init__(self, script=None, payload=None):
        self._script = script or {}
        self.statements = []
        self._payload = payload
        self.closed = False

    def cursor(self):
        return FakeCursor(self._script, self.statements)

    def execute(self, sql):
        self.statements.append(sql)
        return FakeResult(self._payload)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        self.closed = True


def source_script(counts):
    return {f'"{table}"': (count,) for table, count in counts.items()}


FULL_COUNTS = {
    "Couriers": 3,
    "Riders": 100,
    "Users": 100000,
    "Products": 10000,
    "Orders": 1000000,
    "OrderItems": 1999824,
}

READY_JSON = json.dumps(
    {"tableCount": 9, "passed": True, "factRows": 0, "dimDateRows": 0}
)
NOT_READY_JSON = json.dumps({"tableCount": 9, "passed": False, "factRows": 0})


def test_check_source_passes_on_exact_counts():
    conn = FakeConn(source_script(FULL_COUNTS))

    report = check_source(conn)

    assert report["passed"] is True
    assert report["counts"] == FULL_COUNTS
    assert report["countMismatches"] == []
    assert conn.statements
    assert all(s.strip().upper().startswith("SELECT") for s in conn.statements)


def test_check_source_reports_mismatched_table():
    counts = dict(FULL_COUNTS, Users=99999)
    report = check_source(FakeConn(source_script(counts)))

    assert report["passed"] is False
    assert report["countMismatches"] == [
        {"table": "Users", "expected": 100000, "actual": 99999}
    ]


def test_run_preflight_happy_path(monkeypatch):
    monkeypatch.setattr(
        db_module, "connect_source", lambda env=None: FakeConn(source_script(FULL_COUNTS))
    )
    monkeypatch.setattr(
        db_module,
        "connect_warehouse",
        lambda env=None: FakeConn(payload=(READY_JSON,)),
    )

    report = run_preflight()

    assert report["passed"] is True
    assert report["warehouse"]["passed"] is True


def test_run_preflight_unreachable_source_names_setup_script(monkeypatch):
    def boom(env=None):
        raise ConnectionError("source_db unreachable. Run: ./db/scripts/setup_source.sh")

    monkeypatch.setattr(db_module, "connect_source", boom)

    with pytest.raises(PreflightError, match="setup_source.sh"):
        run_preflight()


def test_run_preflight_unreachable_warehouse_names_setup_script(monkeypatch):
    monkeypatch.setattr(
        db_module, "connect_source", lambda env=None: FakeConn(source_script(FULL_COUNTS))
    )

    def boom(env=None):
        raise ConnectionError("dw_db unreachable. Run: ./db/scripts/setup_dw.sh")

    monkeypatch.setattr(db_module, "connect_warehouse", boom)

    with pytest.raises(PreflightError, match="setup_dw.sh"):
        run_preflight()


def test_run_preflight_rejects_count_mismatch(monkeypatch):
    counts = dict(FULL_COUNTS, Orders=0)
    monkeypatch.setattr(
        db_module, "connect_source", lambda env=None: FakeConn(source_script(counts))
    )

    with pytest.raises(PreflightError, match="Orders"):
        run_preflight()


def test_run_preflight_rejects_unready_warehouse(monkeypatch):
    monkeypatch.setattr(
        db_module, "connect_source", lambda env=None: FakeConn(source_script(FULL_COUNTS))
    )
    monkeypatch.setattr(
        db_module,
        "connect_warehouse",
        lambda env=None: FakeConn(payload=(NOT_READY_JSON,)),
    )

    with pytest.raises(PreflightError, match="warehouse not ready"):
        run_preflight()


def test_main_rejects_anything_but_check(monkeypatch):
    import main as main_module

    with pytest.raises(ValueError, match="Usage:"):
        main_module.main([])
    with pytest.raises(ValueError, match="Usage:"):
        main_module.main(["--bogus"])

    monkeypatch.setattr(
        preflight,
        "run_preflight",
        lambda env=None: {"passed": True, "source": {"counts": FULL_COUNTS}, "warehouse": {}},
    )
    assert main_module.main(["--check"]) is None
