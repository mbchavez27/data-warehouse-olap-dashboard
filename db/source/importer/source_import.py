"""Pure-logic port of db/source/importer/source-import.js.

Streams rows from the extended INSERT statements emitted by mysqldump.
The parser deliberately ignores DDL/LOCK metadata and never buffers a full
INSERT statement, which matters for the multi-million-row OrderItems dump.

Byte-parity rules (must stay identical to the JS implementation):
- MySQL escape table and NULL-only-when-unquoted decoding.
- COPY text encoding with backslash escaped first.
- 1-based row numbers and exact error message shapes.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Iterator, List, Optional

MYSQL_ESCAPES = {
    "0": "\0",
    "b": "\b",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "Z": "\x1a",
    "'": "'",
    '"': '"',
    "\\": "\\",
    "%": "%",
    "_": "_",
}


def parse_mysql_rows(
    chunks: Iterable[str],
    *,
    table: str,
    column_count: int,
) -> Iterator[List[Optional[str]]]:
    """Yield one list of raw field values per dumped row.

    ``chunks`` is an iterable of decoded text fragments in order. Callers
    reading bytes must decode with an incremental UTF-8 decoder (see
    :mod:`archive_reader`) so multibyte characters split across chunk
    boundaries survive, mirroring Node's ``setEncoding('utf8')``.
    """
    if not table or not isinstance(column_count, int) or column_count < 1:
        raise TypeError("table and a positive integer column_count are required")

    marker = f"INSERT INTO `{table}` VALUES"
    buffer = ""
    state = "search"  # search | between_rows | in_row
    field_state = "start"  # start | unquoted | quoted | escape | after_quote
    row: List[Optional[str]] = []
    field = ""
    row_number = 0
    saw_insert = False

    def finish_field(quoted: bool) -> None:
        nonlocal field, field_state
        value = field if quoted else field.strip()
        row.append(None if (not quoted and value.upper() == "NULL") else value)
        field = ""
        field_state = "start"

    def finish_row() -> List[Optional[str]]:
        nonlocal row, row_number
        row_number += 1
        if len(row) != column_count:
            raise ValueError(
                f"{table} row {row_number} has {len(row)} fields; "
                f"expected {column_count}"
            )
        completed = row
        row = []
        return completed

    for chunk in chunks:
        buffer += chunk
        offset = 0
        while offset < len(buffer):
            if state == "search":
                found = buffer.find(marker, offset)
                if found == -1:
                    keep = min(len(marker) - 1, len(buffer) - offset)
                    buffer = buffer[len(buffer) - keep :]
                    offset = 0
                    break
                saw_insert = True
                offset = found + len(marker)
                state = "between_rows"
                continue

            ch = buffer[offset]

            if state == "between_rows":
                if ch.isspace() or ch == ",":
                    offset += 1
                    continue
                if ch == "(":
                    row = []
                    field = ""
                    field_state = "start"
                    state = "in_row"
                    offset += 1
                    continue
                if ch == ";":
                    state = "search"
                    offset += 1
                    continue
                raise ValueError(
                    f"{table}: expected row or statement terminator, "
                    f"found {json.dumps(ch)}"
                )

            if field_state == "start":
                if ch.isspace():
                    offset += 1
                    continue
                if ch == "'":
                    field_state = "quoted"
                    offset += 1
                    continue
                field_state = "unquoted"
                continue

            if field_state == "unquoted":
                if ch == ",":
                    finish_field(False)
                    offset += 1
                    continue
                if ch == ")":
                    finish_field(False)
                    completed = finish_row()
                    state = "between_rows"
                    offset += 1
                    yield completed
                    continue
                field += ch
                offset += 1
                continue

            if field_state == "quoted":
                if ch == "\\":
                    field_state = "escape"
                    offset += 1
                    continue
                if ch == "'":
                    field_state = "after_quote"
                    offset += 1
                    continue
                field += ch
                offset += 1
                continue

            if field_state == "escape":
                field += MYSQL_ESCAPES[ch] if ch in MYSQL_ESCAPES else ch
                field_state = "quoted"
                offset += 1
                continue

            if field_state == "after_quote":
                if ch == "'":
                    field += "'"
                    field_state = "quoted"
                    offset += 1
                    continue
                if ch.isspace():
                    offset += 1
                    continue
                if ch == ",":
                    finish_field(True)
                    offset += 1
                    continue
                if ch == ")":
                    finish_field(True)
                    completed = finish_row()
                    state = "between_rows"
                    offset += 1
                    yield completed
                    continue
                raise ValueError(
                    f"{table} row {row_number + 1}: unexpected "
                    f"{json.dumps(ch)} after quoted field"
                )

        if offset >= len(buffer):
            buffer = ""

    if not saw_insert:
        raise ValueError(f"{table}: no matching INSERT statement found")
    if state != "search":
        raise ValueError(f"{table}: unexpected end of dump while parsing {state}")


def encode_copy_row(row: List[Optional[str]]) -> str:
    """Encode one row for PostgreSQL COPY text format (tab delimiter)."""
    parts = []
    for value in row:
        if value is None:
            parts.append("\\N")
            continue
        parts.append(
            value.replace("\\", "\\\\")
            .replace("\t", "\\t")
            .replace("\n", "\\n")
            .replace("\r", "\\r")
        )
    return "\t".join(parts) + "\n"


def assess_database(
    actual: Dict[str, Any], expected_counts: Dict[str, int]
) -> Dict[str, Any]:
    """Check row counts are exact and every orphan relationship is zero."""
    count_mismatches = [
        {"table": table, "expected": expected, "actual": actual["counts"][table]}
        for table, expected in expected_counts.items()
        if actual["counts"][table] != expected
    ]
    orphan_violations = [
        {"relationship": relationship, "count": count}
        for relationship, count in actual["orphans"].items()
        if count != 0
    ]
    return {
        "passed": not count_mismatches and not orphan_violations,
        "countMismatches": count_mismatches,
        "orphanViolations": orphan_violations,
    }


def assess_source_schema(
    actual: Dict[str, Any],
    expected_columns: Dict[str, int],
    expected_shape: Dict[str, Any],
) -> Dict[str, Any]:
    """Check the replicated table and constraint shape."""
    violations = []

    def check(name: str, expected: Any, value: Any) -> None:
        if value != expected:
            violations.append({"check": name, "expected": expected, "actual": value})

    check("tableCount", len(expected_columns), actual["tableCount"])
    for table, count in expected_columns.items():
        check(f"{table}.columnCount", count, actual["columnCounts"][table])
    check("primaryKeyCount", expected_shape["primaryKeyCount"], actual["primaryKeyCount"])
    check("foreignKeyCount", expected_shape["foreignKeyCount"], actual["foreignKeyCount"])
    check(
        "identityColumnCount",
        expected_shape["identityColumnCount"],
        actual["identityColumnCount"],
    )
    check("OrderItems.ProductIdIndex", True, actual["productIdIndex"])

    return {"passed": not violations, "violations": violations}
