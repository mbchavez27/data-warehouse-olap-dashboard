"""DB-free tests for the --optimize phase that rebuilds the reports' summary views."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from load import summaries


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = None
        self._row = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql):
        self.conn.executed.append(sql)
        if sql is summaries.VERIFY_SQL:
            self.description = [SimpleNamespace(name=name) for name in self.conn.checks]
            self._row = tuple(self.conn.checks.values())
        elif sql.startswith("SELECT count(*) FROM"):
            self._row = (self.conn.view_rows,)

    def fetchone(self):
        return self._row


class FakeConnection:
    """Records what ran and whether the transaction committed."""

    def __init__(self, checks=None, dbname="dw_db"):
        self.info = SimpleNamespace(dbname=dbname)
        self.checks = checks or {"rider_day_orders": True, "customer_value": True}
        self.view_rows = 42
        self.executed = []
        self.committed = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *rest):
        self.committed = exc_type is None
        return False

    def cursor(self):
        return FakeCursor(self)


def fake_files(name):
    return {
        "01_indexes.sql": "\\timing on\nDROP INDEX IF EXISTS ix_item_rider;\n",
        "02_config.sql": "ALTER DATABASE dw_db SET jit = off;\nALTER DATABASE dw_db SET work_mem = '64MB';\n",
        "03_preagg.sql": '\\timing on\nCREATE MATERIALIZED VIEW "AGG_RIDER_DAY" AS SELECT 1;\n',
    }[name]


def test_prepare_drops_psql_meta_commands():
    prepared = summaries.prepare("\\timing on\nSELECT 1;\n  \\echo done\nSELECT 2;", "dw_db")
    assert "\\" not in prepared
    assert "SELECT 1;" in prepared and "SELECT 2;" in prepared


def test_prepare_points_the_settings_at_the_connected_database():
    prepared = summaries.prepare("ALTER DATABASE dw_db SET jit = off;", "hosted_dw")
    assert prepared == 'ALTER DATABASE "hosted_dw" SET jit = off;'
    assert summaries.prepare("ALTER DATABASE dw_db SET jit = off;", 'odd"name') == (
        'ALTER DATABASE "odd""name" SET jit = off;'
    )


def test_build_runs_the_three_files_in_order_verifies_and_commits():
    conn = FakeConnection()
    summary = summaries.run_summary_build(connect=lambda: conn, read_sql=fake_files)

    scripts = conn.executed[:3]
    assert "DROP INDEX" in scripts[0] and "ALTER DATABASE" in scripts[1] and "MATERIALIZED VIEW" in scripts[2]
    assert all("\\timing" not in script for script in scripts)
    assert conn.executed[3] is summaries.VERIFY_SQL
    assert conn.committed is True
    assert summary["views"] == {view: 42 for view in summaries.SUMMARY_VIEWS}
    assert all(summary["checks"].values())


def test_a_view_that_does_not_match_the_facts_rolls_everything_back():
    conn = FakeConnection(checks={"rider_day_orders": True, "product_units": False})
    with pytest.raises(RuntimeError, match="product_units"):
        summaries.run_summary_build(connect=lambda: conn, read_sql=fake_files)
    assert conn.committed is False


def test_the_real_optimize_files_build_every_view_the_reports_read():
    preagg = (summaries.OPTIMIZE_DIR / "03_preagg.sql").read_text(encoding="utf-8")
    for name in summaries.OPTIMIZE_FILES:
        assert (summaries.OPTIMIZE_DIR / name).is_file(), name
    for view in summaries.SUMMARY_VIEWS:
        assert f'CREATE MATERIALIZED VIEW "{view}"' in preagg, view

    queries = summaries.config.REPO_ROOT / "olap" / "queries"
    read = {view for view in summaries.SUMMARY_VIEWS for sql in queries.rglob("*.sql") if view in sql.read_text()}
    assert read == set(summaries.SUMMARY_VIEWS), "every view built is one the report queries read"
