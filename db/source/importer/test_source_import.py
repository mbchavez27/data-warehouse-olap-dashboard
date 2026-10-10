"""Pytest mirrors of db/source/importer/source-import.test.js plus new edge tests.

Mirrors keep the same cases and expectations as the JS suite so the port is
held to byte-parity. New tests cover paths the JS suite never exercised:
multi-chunk delivery, doubled-quote fields, and truncated dumps.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from source_import import (
    assess_database,
    assess_source_schema,
    encode_copy_row,
    parse_mysql_rows,
)


def collect(sql, **options):
    return list(parse_mysql_rows([sql], **options))


def test_parses_multiple_inserts_ignoring_metadata():
    sql = "\n".join(
        [
            "-- MySQL dump header",
            "LOCK TABLES `Couriers` WRITE;",
            "INSERT INTO `Couriers` VALUES (1,'JNT','2025-09-22 16:56:36','2025-09-22 16:56:36'),",
            "(2,'LBCD','2025-09-22 16:56:36','2025-09-22 16:56:36');",
            "UNLOCK TABLES;",
            "INSERT INTO `Couriers` VALUES (3,NULL,'2025-09-22 16:56:36','2025-09-22 16:56:36');",
        ]
    )

    assert collect(sql, table="Couriers", column_count=4) == [
        ["1", "JNT", "2025-09-22 16:56:36", "2025-09-22 16:56:36"],
        ["2", "LBCD", "2025-09-22 16:56:36", "2025-09-22 16:56:36"],
        ["3", None, "2025-09-22 16:56:36", "2025-09-22 16:56:36"],
    ]


def test_decodes_mysql_escapes_preserving_punctuation_and_unicode():
    sql = (
        "INSERT INTO `Users` VALUES "
        "(99,'O\\'Connell','comma, (paren)','slash\\\\tab\\tline\\nzero\\0quote\\\"',"
        "'address1','address2','Makati','PH','1000','0917','2000-01-01','F',"
        "'2025-01-01 00:00:00','2025-01-01 00:00:00'),"
        "(100,'José','ok',NULL,'x','y','city','z','1','2','2001-01-01','M',"
        "'2025-01-01 00:00:00','2025-01-01 00:00:00');"
    )

    rows = collect(sql, table="Users", column_count=14)
    assert rows[0][1] == "O'Connell"
    assert rows[0][2] == "comma, (paren)"
    assert rows[0][3] == "slash\\tab\tline\nzero\0quote\""
    assert rows[1][1] == "José"
    assert rows[1][3] is None


def test_rejects_row_with_wrong_field_count():
    sql = "INSERT INTO `Couriers` VALUES (1,'missing timestamps');"

    with pytest.raises(
        ValueError, match=r"Couriers row 1 has 2 fields; expected 4"
    ):
        collect(sql, table="Couriers", column_count=4)


def test_encode_copy_row_keeps_null_distinct_from_string_null():
    assert (
        encode_copy_row(["a\tb", "line\nnext", "slash\\value", None, "NULL"])
        == "a\\tb\tline\\nnext\tslash\\\\value\t\\N\tNULL\n"
    )


def test_encode_copy_row_escapes_carriage_return():
    assert encode_copy_row(["a\rb"]) == "a\\rb\n"


def test_assess_database_passes_only_on_exact_counts_and_zero_orphans():
    expected = {"Couriers": 3, "Riders": 100}

    assert assess_database(
        {"counts": {"Couriers": 3, "Riders": 100}, "orphans": {"riderCourier": 0}},
        expected,
    ) == {"passed": True, "countMismatches": [], "orphanViolations": []}


def test_assess_database_reports_mismatches_and_every_orphan():
    assessment = assess_database(
        {
            "counts": {"Couriers": 2, "Riders": 100},
            "orphans": {"riderCourier": 4, "orderUser": 0, "itemProduct": 7},
        },
        {"Couriers": 3, "Riders": 100},
    )

    assert assessment["passed"] is False
    assert assessment["countMismatches"] == [
        {"table": "Couriers", "expected": 3, "actual": 2}
    ]
    assert assessment["orphanViolations"] == [
        {"relationship": "riderCourier", "count": 4},
        {"relationship": "itemProduct", "count": 7},
    ]


def test_assess_schema_accepts_only_replicated_shape():
    expected_columns = {"Couriers": 4, "Riders": 9}
    valid = {
        "tableCount": 2,
        "columnCounts": {"Couriers": 4, "Riders": 9},
        "primaryKeyCount": 2,
        "foreignKeyCount": 2,
        "identityColumnCount": 2,
        "productIdIndex": True,
    }

    assert assess_source_schema(
        valid,
        expected_columns,
        {"primaryKeyCount": 2, "foreignKeyCount": 2, "identityColumnCount": 2},
    ) == {"passed": True, "violations": []}


def test_assess_schema_reports_missing_tables_columns_and_index():
    assessment = assess_source_schema(
        {
            "tableCount": 1,
            "columnCounts": {"Couriers": 3, "Riders": 9},
            "primaryKeyCount": 1,
            "foreignKeyCount": 2,
            "identityColumnCount": 2,
            "productIdIndex": False,
        },
        {"Couriers": 4, "Riders": 9},
        {"primaryKeyCount": 2, "foreignKeyCount": 2, "identityColumnCount": 2},
    )

    assert assessment["passed"] is False
    assert assessment["violations"] == [
        {"check": "tableCount", "expected": 2, "actual": 1},
        {"check": "Couriers.columnCount", "expected": 4, "actual": 3},
        {"check": "primaryKeyCount", "expected": 2, "actual": 1},
        {"check": "OrderItems.ProductIdIndex", "expected": True, "actual": False},
    ]


def test_parse_identical_rows_across_arbitrary_chunk_splits():
    sql = (
        "-- header\n"
        "INSERT INTO `Couriers` VALUES (1,'JNT','2025-09-22 16:56:36','2025-09-22 16:56:36'),"
        "(2,'LBCD','2025-09-22 16:56:36','2025-09-22 16:56:36');\n"
        "INSERT INTO `Couriers` VALUES (3,NULL,'2025-09-22 16:56:36','2025-09-22 16:56:36');"
    )
    expected = collect(sql, table="Couriers", column_count=4)

    for width in (1, 7, 64):
        chunks = [sql[i : i + width] for i in range(0, len(sql), width)]
        assert (
            list(parse_mysql_rows(chunks, table="Couriers", column_count=4))
            == expected
        )


def test_parse_doubled_quotes_and_control_escapes():
    sql = (
        "INSERT INTO `Couriers` VALUES "
        "(1,'it''s quoted','2025-09-22 16:56:36','2025-09-22 16:56:36'),"
        "(2,'pct\\%under\\_bell\\x07sub\\Z','2025-09-22 16:56:36','2025-09-22 16:56:36');"
    )

    rows = collect(sql, table="Couriers", column_count=4)
    assert rows[0][1] == "it's quoted"
    # \% and \_ decode to % and _; \x is not a MySQL escape so only the
    # backslash drops; \Z decodes to ASCII 26 (same as the JS implementation).
    assert rows[1][1] == "pct%under_bellx07sub\x1a"


def test_parse_null_with_surrounding_spaces():
    sql = "INSERT INTO `Couriers` VALUES (1,  NULL  ,'2025-09-22 16:56:36','2025-09-22 16:56:36');"

    assert collect(sql, table="Couriers", column_count=4)[0][1] is None


def test_parse_rejects_dump_without_matching_insert():
    with pytest.raises(ValueError, match="no matching INSERT statement found"):
        collect("LOCK TABLES `Couriers` WRITE;\n", table="Couriers", column_count=4)


def test_parse_rejects_truncated_dump_mid_row():
    with pytest.raises(ValueError, match="unexpected end of dump"):
        collect(
            "INSERT INTO `Couriers` VALUES (1,'JNT','2025-09-22",
            table="Couriers",
            column_count=4,
        )


def test_parse_rejects_garbage_between_rows():
    with pytest.raises(ValueError, match="expected row or statement terminator"):
        collect(
            "INSERT INTO `Couriers` VALUES (1,'JNT','a','b') BOGUS;",
            table="Couriers",
            column_count=4,
        )


def test_parse_requires_table_and_column_count():
    with pytest.raises(TypeError):
        list(parse_mysql_rows(["x"], table="", column_count=4))
    with pytest.raises(TypeError):
        list(parse_mysql_rows(["x"], table="Couriers", column_count=0))


def test_canonical_ddl_drops_all_six_tables_before_recreate():
    ddl = (
        Path(__file__).resolve().parent.parent / "init" / "01_source_schema.sql"
    ).read_text(encoding="utf-8")

    for table in ("OrderItems", "Orders", "Products", "Users", "Riders", "Couriers"):
        assert f'DROP TABLE IF EXISTS "{table}" CASCADE;' in ddl, table
    # Every dropped table must be recreated later in the same script, and
    # drops must precede the first CREATE so re-runs are idempotent.
    first_create = ddl.index("CREATE TABLE")
    for table in ("OrderItems", "Orders", "Products", "Users", "Riders", "Couriers"):
        assert f'DROP TABLE IF EXISTS "{table}" CASCADE;' in ddl[:first_create]
        assert f'CREATE TABLE "{table}" (' in ddl
