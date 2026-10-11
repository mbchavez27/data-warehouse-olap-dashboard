"""Shared fixtures. `test_db` gives load tests a disposable PostgreSQL database.

It never touches source_db or dw_db: the DSN comes from ETL_TEST_DSN
(default: the dw_test database on the local warehouse container), and the
fixture refuses to run against a database named source_db or dw_db. Each test
gets both schemas freshly applied from the repo's own DDL files, so source
tables ("Riders", ...) and warehouse tables ("DIM_RIDER", ...) live side by
side. Without a reachable database the tests skip, unless
ETL_REQUIRE_DB_TESTS=1 (set in CI), which turns the skip into a failure.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
import pytest

ETL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ETL_DIR))

from core import config

DEFAULT_TEST_DSN = "host=localhost port=5434 dbname=dw_test user=postgres password=postgres"
SOURCE_DDL = config.REPO_ROOT / "db" / "source" / "init" / "01_source_schema.sql"
DW_DDL = config.REPO_ROOT / "db" / "dw" / "init" / "01_dw_schema.sql"
PROTECTED = {"source_db", "dw_db"}


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    dsn = os.environ.get("ETL_TEST_DSN", DEFAULT_TEST_DSN)
    try:
        admin = psycopg.connect(dsn, autocommit=True)
    except psycopg.OperationalError as error:
        if os.environ.get("ETL_REQUIRE_DB_TESTS") == "1":
            raise
        pytest.skip(f"test database unavailable ({dsn}): {error}")
    with admin:
        if admin.info.dbname in PROTECTED:
            pytest.fail(f"refusing to run load tests against {admin.info.dbname}")
        admin.execute(SOURCE_DDL.read_text(encoding="utf-8"))
        admin.execute(DW_DDL.read_text(encoding="utf-8"))

    from core import rejects

    monkeypatch.setattr(rejects, "LEDGER_PATH", tmp_path / "etl-rejects.json")
    yield dsn
