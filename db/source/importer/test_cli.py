"""Tests for db/source/importer/cli.py: guards, env parsing, contracts.

Live Docker tests are excluded: verify/import/validate run against the real
ZIP and database in the Stage 2 evidence gate, not in unit tests. What is
pinned here: CLI guards fail before any I/O, .env parsing matches loadEnv,
TABLES matches the canonical DDL column order, and validation_sql() cannot
drift from the reviewed query.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cli
from cli import load_env, parse_args, usage, validation_sql

IMPORTER_DIR = Path(__file__).resolve().parent
DDL_PATH = IMPORTER_DIR.parent / "init" / "01_source_schema.sql"


def test_parse_args_command_and_flags():
    command, options = parse_args(
        ["import", "--archive", "a.zip", "--reset", "--output", "o.json"]
    )

    assert command == "import"
    assert options == {"archive": "a.zip", "reset": True, "output": "o.json"}


def test_parse_args_rejects_positional_and_dangling_values():
    with pytest.raises(ValueError, match="unexpected argument: nope"):
        parse_args(["verify", "nope"])
    with pytest.raises(ValueError, match="missing value for --archive"):
        parse_args(["verify", "--archive"])


def test_main_rejects_unknown_command_before_any_io():
    with pytest.raises(ValueError, match="Usage:"):
        cli.main(["bogus"])


def test_main_requires_archive_for_verify_and_import():
    with pytest.raises(ValueError, match="--archive is required"):
        cli.main(["verify"])
    with pytest.raises(ValueError, match="--archive is required"):
        cli.main(["import", "--reset"])


def test_main_requires_reset_for_import():
    with pytest.raises(ValueError, match="requires explicit --reset"):
        cli.main(["import", "--archive", "a.zip"])


def test_usage_documents_all_three_commands():
    text = usage()

    assert "verify --archive" in text
    assert "import --archive" in text and "--reset" in text
    assert "validate" in text


def test_load_env_parses_values_and_ignores_noise(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n"
        "\n"
        "SOURCE_USER=app\n"
        "SOURCE_DB = source_db\n"
        "PASSWORD=a=b=c\n"
        "BROKENLINE\n",
        encoding="utf-8",
    )

    assert load_env(env_file) == {
        "SOURCE_USER": "app",
        "SOURCE_DB": "source_db",
        "PASSWORD": "a=b=c",
    }


def test_load_env_missing_file_yields_empty_defaults(tmp_path):
    assert load_env(tmp_path / ".env") == {}


def _ddl_column_order(ddl: str, table: str) -> list:
    block = re.search(
        rf'CREATE TABLE "{table}" \((.*?)\n\);', ddl, re.DOTALL
    ).group(1)
    columns = []
    for line in block.splitlines():
        stripped = line.strip().rstrip(",")
        if not stripped or stripped.startswith(("PRIMARY KEY", "FOREIGN KEY", "CONSTRAINT", "UNIQUE", "CHECK")):
            continue
        columns.append(stripped.split()[0].strip('"'))
    return columns


def test_tables_match_canonical_ddl_column_order():
    ddl = DDL_PATH.read_text(encoding="utf-8")

    assert [t["name"] for t in cli.TABLES] == [
        "Couriers",
        "Riders",
        "Users",
        "Products",
        "Orders",
        "OrderItems",
    ]
    assert {t["name"]: t["expected"] for t in cli.TABLES} == {
        "Couriers": 3,
        "Riders": 100,
        "Users": 100000,
        "Products": 10000,
        "Orders": 1000000,
        "OrderItems": 1999824,
    }
    for table in cli.TABLES:
        assert table["columns"] == _ddl_column_order(ddl, table["name"]), table["name"]


EXPECTED_VALIDATION_SQL = """
SELECT json_build_object(
  'counts', json_build_object(
    'Couriers', (SELECT count(*) FROM "Couriers"),
    'Riders', (SELECT count(*) FROM "Riders"),
    'Users', (SELECT count(*) FROM "Users"),
    'Products', (SELECT count(*) FROM "Products"),
    'Orders', (SELECT count(*) FROM "Orders"),
    'OrderItems', (SELECT count(*) FROM "OrderItems")
  ),
  'orphans', json_build_object(
    'riderCourier', (SELECT count(*) FROM "Riders" child LEFT JOIN "Couriers" parent ON parent."id" = child."courierId" WHERE child."courierId" IS NOT NULL AND parent."id" IS NULL),
    'orderUser', (SELECT count(*) FROM "Orders" child LEFT JOIN "Users" parent ON parent."id" = child."userId" WHERE child."userId" IS NOT NULL AND parent."id" IS NULL),
    'orderRider', (SELECT count(*) FROM "Orders" child LEFT JOIN "Riders" parent ON parent."id" = child."deliveryRiderId" WHERE child."deliveryRiderId" IS NOT NULL AND parent."id" IS NULL),
    'itemOrder', (SELECT count(*) FROM "OrderItems" child LEFT JOIN "Orders" parent ON parent."id" = child."OrderId" WHERE parent."id" IS NULL),
    'itemProduct', (SELECT count(*) FROM "OrderItems" child LEFT JOIN "Products" parent ON parent."id" = child."ProductId" WHERE parent."id" IS NULL)
  ),
  'schema', json_build_object(
    'tableCount', (SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name = ANY (ARRAY['Couriers','Riders','Users','Products','Orders','OrderItems'])),
    'columnCounts', json_build_object(
      'Couriers', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'Couriers'),
      'Riders', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'Riders'),
      'Users', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'Users'),
      'Products', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'Products'),
      'Orders', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'Orders'),
      'OrderItems', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'OrderItems')
    ),
    'primaryKeyCount', (SELECT count(*) FROM pg_constraint c JOIN pg_class r ON r.oid = c.conrelid JOIN pg_namespace n ON n.oid = r.relnamespace WHERE n.nspname = 'public' AND r.relname = ANY (ARRAY['Couriers','Riders','Users','Products','Orders','OrderItems']) AND c.contype = 'p'),
    'foreignKeyCount', (SELECT count(*) FROM pg_constraint c JOIN pg_class r ON r.oid = c.conrelid JOIN pg_namespace n ON n.oid = r.relnamespace WHERE n.nspname = 'public' AND r.relname = ANY (ARRAY['Couriers','Riders','Users','Products','Orders','OrderItems']) AND c.contype = 'f'),
    'identityColumnCount', (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = ANY (ARRAY['Couriers','Riders','Users','Products','Orders']) AND is_identity = 'YES'),
    'productIdIndex', (to_regclass('public."OrderItems_ProductId_idx"') IS NOT NULL)
  )
)::text;
"""


def test_validation_sql_matches_reviewed_query():
    assert validation_sql() == EXPECTED_VALIDATION_SQL
