#!/usr/bin/env python3
"""Source database importer CLI. Exact port of db/source/importer/cli.js.

Streams the six MySQL dumps out of the official ZIP and loads them into the
local PostgreSQL ``source_db`` with per-archive verification, an atomic
single-transaction import, and independent database validation. Evidence
lands in ``evidence/`` in the same JSON shape as the JS implementation.

Divergence from JS (message-level only, behavior identical):
- Pipe failures surface captured psql stderr instead of bare ``EPIPE``.
- Archive entries are read with stdlib ``zipfile`` (see archive_reader),
  so no external ``tar`` binary is needed.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from archive_reader import iter_archive_text, list_archive_entries, match_entries
from source_import import (
    assess_database,
    assess_source_schema,
    encode_copy_row,
    parse_mysql_rows,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SOURCE_SCHEMA = Path(__file__).resolve().parent.parent / "init" / "01_source_schema.sql"
DEFAULT_REPORT = REPO_ROOT / "evidence" / "source-import-report.json"
FAILURE_LOG = REPO_ROOT / "evidence" / "source-import-failures.log"
EXPECTED_SHA256 = "a10f11865ef05253672090e4d73d15a3d7fad96adffe6dbc6fb8c09c8037e862"
CONTAINER = "stadvdb-mco1-source-db"

# Order is load-bearing: each orphan check reads ID sets completed earlier
# (Couriers before Riders, Users+Riders before Orders, Orders+Products
# before OrderItems). Column lists must match the dump field order.
TABLES = [
    {
        "name": "Couriers",
        "file": "faker_Couriers.sql",
        "expected": 3,
        "columns": ["id", "name", "createdAt", "updatedAt"],
    },
    {
        "name": "Riders",
        "file": "faker_Riders.sql",
        "expected": 100,
        "columns": [
            "id",
            "firstName",
            "lastName",
            "vehicleType",
            "courierId",
            "age",
            "gender",
            "createdAt",
            "updatedAt",
        ],
    },
    {
        "name": "Users",
        "file": "faker_Users.sql",
        "expected": 100000,
        "columns": [
            "id",
            "username",
            "firstName",
            "lastName",
            "address1",
            "address2",
            "city",
            "country",
            "zipCode",
            "phoneNumber",
            "dateOfBirth",
            "gender",
            "createdAt",
            "updatedAt",
        ],
    },
    {
        "name": "Products",
        "file": "faker_Products.sql",
        "expected": 10000,
        "columns": [
            "id",
            "productCode",
            "category",
            "description",
            "name",
            "price",
            "createdAt",
            "updatedAt",
        ],
    },
    {
        "name": "Orders",
        "file": "faker_Orders.sql",
        "expected": 1000000,
        "columns": [
            "id",
            "orderNumber",
            "userId",
            "deliveryDate",
            "deliveryRiderId",
            "createdAt",
            "updatedAt",
        ],
    },
    {
        "name": "OrderItems",
        "file": "faker_OrderItems.sql",
        "expected": 1999824,
        "columns": ["quantity", "notes", "createdAt", "updatedAt", "OrderId", "ProductId"],
    },
]


def parse_args(argv: List[str]) -> Tuple[Optional[str], Dict[str, Any]]:
    """Split ``[command, --flag value ...]`` like the JS parseArgs."""
    command = argv[0] if argv else None
    options: Dict[str, Any] = {}
    i = 1
    while i < len(argv):
        token = argv[i]
        if not token.startswith("--"):
            raise ValueError(f"unexpected argument: {token}")
        key = token[2:]
        if key == "reset":
            options["reset"] = True
            i += 1
            continue
        if i + 1 >= len(argv):
            raise ValueError(f"missing value for {token}")
        options[key] = argv[i + 1]
        i += 2
    return command, options


def usage() -> str:
    return "\n".join(
        [
            "Usage:",
            "  uv run --project db python db/source/importer/cli.py verify --archive <MCO1_dataset_ecommerce.zip> [--output <report.json>]",
            "  uv run --project db python db/source/importer/cli.py import --archive <MCO1_dataset_ecommerce.zip> --reset [--output <report.json>]",
            "  uv run --project db python db/source/importer/cli.py validate [--output <report.json>]",
            "",
            "The --reset flag is mandatory for import because it drops and recreates all six source tables.",
        ]
    )


def load_env(path: Path) -> Dict[str, str]:
    """Parse KEY=value lines; missing file yields {} (mirrors loadEnv)."""
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        equals = line.find("=")
        if equals < 1:
            continue
        values[line[:equals].strip()] = line[equals + 1 :].strip()
    return values


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def for_each_archive_row(
    archive: str,
    entry: str,
    table: Dict[str, Any],
    on_row: Callable[[List[Optional[str]], int], None],
) -> int:
    """Stream parsed rows of one dump entry through ``on_row``; return count."""
    count = 0
    rows = parse_mysql_rows(
        iter_archive_text(archive, entry),
        table=table["name"],
        column_count=len(table["columns"]),
    )
    for row in rows:
        count += 1
        on_row(row, count)
    return count


def verify_archive(archive: str) -> Dict[str, Any]:
    resolved = str(Path(archive).resolve())
    if not os.path.isfile(resolved):
        raise ValueError(f"archive is not a file: {resolved}")

    digest = sha256_of(resolved)
    entries = match_entries(
        list_archive_entries(resolved),
        {table["name"]: table["file"] for table in TABLES},
    )
    counts: Dict[str, int] = {}
    duplicate_ids: Dict[str, int] = {}
    archive_orphans = {
        "riderCourier": 0,
        "orderUser": 0,
        "orderRider": 0,
        "itemOrder": 0,
        "itemProduct": 0,
    }
    ids: Dict[str, set] = {
        name: set() for name in ("Couriers", "Riders", "Users", "Products", "Orders")
    }

    for table in TABLES:
        name = table["name"]
        if name in ids:
            duplicate_ids[name] = 0

        def check(row: List[Optional[str]], _n: int) -> None:
            if name in ids:
                if row[0] in ids[name]:
                    duplicate_ids[name] += 1
                ids[name].add(row[0])
            if name == "Riders" and row[4] is not None and row[4] not in ids["Couriers"]:
                archive_orphans["riderCourier"] += 1
            if name == "Orders":
                if row[2] is not None and row[2] not in ids["Users"]:
                    archive_orphans["orderUser"] += 1
                if row[4] is not None and row[4] not in ids["Riders"]:
                    archive_orphans["orderRider"] += 1
            if name == "OrderItems":
                if row[4] not in ids["Orders"]:
                    archive_orphans["itemOrder"] += 1
                if row[5] not in ids["Products"]:
                    archive_orphans["itemProduct"] += 1

        counts[name] = for_each_archive_row(resolved, entries[name], table, check)
        print(f"Verified {name}: {counts[name]:,} rows")

    expected_counts = {table["name"]: table["expected"] for table in TABLES}
    assessment = assess_database({"counts": counts, "orphans": archive_orphans}, expected_counts)
    duplicate_violations = [
        {"table": table, "count": count}
        for table, count in duplicate_ids.items()
        if count > 0
    ]
    hash_matches = digest == EXPECTED_SHA256

    return {
        "file": os.path.basename(resolved),
        "bytes": os.path.getsize(resolved),
        "sha256": digest,
        "expectedSha256": EXPECTED_SHA256,
        "hashMatches": hash_matches,
        "entries": entries,
        "counts": counts,
        "expectedCounts": expected_counts,
        "countMismatches": assessment["countMismatches"],
        "orphans": archive_orphans,
        "duplicateIds": duplicate_ids,
        "passed": hash_matches and assessment["passed"] and not duplicate_violations,
    }


def _docker_base_args(db: Dict[str, str]) -> List[str]:
    return ["exec", "-i", CONTAINER, "psql", "-X", "-v", "ON_ERROR_STOP=1"]


def require_healthy_container() -> None:
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", CONTAINER],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"{CONTAINER} is unavailable. Run: docker compose up -d --wait source_db\n{exc}"
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"{CONTAINER} is unavailable. Run: docker compose up -d --wait source_db\n"
            f"{result.stderr.strip()}"
        )
    if result.stdout.strip() != "healthy":
        raise RuntimeError(
            f"{CONTAINER} is {json.dumps(result.stdout.strip())}; expected \"healthy\""
        )


def _drain_to(stream: Any, sink: List[str]) -> None:
    for chunk in iter(lambda: stream.read(65536), ""):
        sink.append(chunk)


def import_archive(
    archive: str, entries: Dict[str, str], db: Dict[str, str]
) -> Dict[str, Any]:
    require_healthy_container()
    schema_sql = SOURCE_SCHEMA.read_text(encoding="utf-8")
    proc = subprocess.Popen(
        ["docker"] + _docker_base_args(db) + ["-U", db["user"], "-d", db["name"]],
        cwd=str(REPO_ROOT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
    stdout_chunks: List[str] = []
    stderr_chunks: List[str] = []
    drainers = [
        threading.Thread(target=_drain_to, args=(proc.stdout, stdout_chunks)),
        threading.Thread(target=_drain_to, args=(proc.stderr, stderr_chunks)),
    ]
    for thread in drainers:
        thread.start()

    def stop() -> Tuple[int, str, str]:
        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except BrokenPipeError:
            pass
        proc.kill()
        for thread in drainers:
            thread.join()
        code = proc.wait()
        return code, "".join(stdout_chunks), "".join(stderr_chunks)

    def finish() -> Tuple[int, str, str]:
        assert proc.stdin is not None
        proc.stdin.close()
        for thread in drainers:
            thread.join()
        return proc.wait(), "".join(stdout_chunks), "".join(stderr_chunks)

    try:
        write = proc.stdin.write
        write("\\set ON_ERROR_STOP on\nBEGIN;\n")
        write(f"{schema_sql}\n")

        for table in TABLES:
            name = table["name"]
            quoted = ", ".join(f'"{column}"' for column in table["columns"])
            write(
                f'COPY "{name}" ({quoted}) FROM STDIN '
                f"WITH (FORMAT text, DELIMITER E'\\t', NULL '\\N');\n"
            )
            count = for_each_archive_row(
                archive,
                entries[name],
                table,
                lambda row, _n: write(encode_copy_row(row)),
            )
            if count != table["expected"]:
                raise ValueError(
                    f"{name}: refusing import because {count} rows were parsed; "
                    f"expected {table['expected']}"
                )
            write("\\.\n")
            print(f"Imported {name}: {count:,} rows")

        for table in [t for t in TABLES if t["name"] != "OrderItems"]:
            name = table["name"]
            write(
                f"SELECT setval(pg_get_serial_sequence('\"{name}\"', 'id'), "
                f'COALESCE(MAX("id"), 1), MAX("id") IS NOT NULL) FROM "{name}";\n'
            )
        write("COMMIT;\n")
        code, stdout, stderr = finish()
    except BaseException as exc:
        code, _stdout, stderr = stop()
        detail = stderr.strip().splitlines()
        tail = " | ".join(detail[-5:]) if detail else "psql produced no stderr"
        raise RuntimeError(f"import aborted ({type(exc).__name__}: {exc}): {tail}") from exc

    if code != 0:
        raise RuntimeError(f"atomic PostgreSQL import failed ({code}): {stderr.strip()}")
    return {"transaction": "committed", "psqlOutput": stdout.strip().splitlines()[-20:]}


def validation_sql() -> str:
    return """
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


def validate_database(db: Dict[str, str]) -> Dict[str, Any]:
    require_healthy_container()
    result = subprocess.run(
        ["docker"]
        + _docker_base_args(db)
        + ["-U", db["user"], "-d", db["name"], "-At", "-c", validation_sql()],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"database validation query failed ({result.returncode}): "
            f"{result.stderr.strip()}"
        )
    actual = json.loads(result.stdout.strip())
    for group in (actual["counts"], actual["orphans"]):
        for key in group:
            group[key] = int(group[key])
    actual["schema"]["tableCount"] = int(actual["schema"]["tableCount"])
    actual["schema"]["primaryKeyCount"] = int(actual["schema"]["primaryKeyCount"])
    actual["schema"]["foreignKeyCount"] = int(actual["schema"]["foreignKeyCount"])
    actual["schema"]["identityColumnCount"] = int(actual["schema"]["identityColumnCount"])
    for key in actual["schema"]["columnCounts"]:
        actual["schema"]["columnCounts"][key] = int(actual["schema"]["columnCounts"][key])
    expected = {table["name"]: table["expected"] for table in TABLES}
    expected_columns = {table["name"]: len(table["columns"]) for table in TABLES}
    data_assessment = assess_database(actual, expected)
    schema_assessment = assess_source_schema(
        actual["schema"],
        expected_columns,
        {"primaryKeyCount": 6, "foreignKeyCount": 2, "identityColumnCount": 5},
    )
    return {
        **actual,
        "countMismatches": data_assessment["countMismatches"],
        "orphanViolations": data_assessment["orphanViolations"],
        "schemaViolations": schema_assessment["violations"],
        "passed": data_assessment["passed"] and schema_assessment["passed"],
    }


def write_report(path: Optional[str], report: Dict[str, Any]) -> None:
    resolved = Path(path).resolve() if path else DEFAULT_REPORT
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Evidence written to {os.path.relpath(resolved, REPO_ROOT)}")


def record_failure(command: Optional[str], error: BaseException) -> None:
    FAILURE_LOG.parent.mkdir(parents=True, exist_ok=True)
    detail = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    ).replace("\n", " | ")
    with FAILURE_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{_utc_now_iso()}\t{command or 'unknown'}\t{detail}\n")


def main(argv: Optional[List[str]] = None) -> None:
    command, options = parse_args(sys.argv[1:] if argv is None else argv)
    if command not in ("verify", "import", "validate"):
        raise ValueError(usage())
    if command in ("verify", "import") and not options.get("archive"):
        raise ValueError(f"--archive is required\n\n{usage()}")
    if command == "import" and not options.get("reset"):
        raise ValueError(f"import is destructive and requires explicit --reset\n\n{usage()}")

    env = load_env(REPO_ROOT / ".env")
    db = {"user": env.get("SOURCE_USER", "postgres"), "name": env.get("SOURCE_DB", "source_db")}
    report: Dict[str, Any] = {
        "schemaVersion": 1,
        "generatedAt": _utc_now_iso(),
        "command": command,
        "sourceDatabase": {
            "engine": "PostgreSQL",
            "version": 16,
            "container": CONTAINER,
            "database": db["name"],
        },
        "importFailures": [],
    }

    if command in ("verify", "import"):
        report["archive"] = verify_archive(str(options["archive"]))
        if not report["archive"]["passed"]:
            raise RuntimeError(
                "archive verification failed; inspect reported hash, counts, "
                "duplicates, and orphans"
            )
    if command == "import":
        report["import"] = import_archive(
            str(Path(str(options["archive"])).resolve()),
            report["archive"]["entries"],
            db,
        )
    if command in ("import", "validate"):
        report["database"] = validate_database(db)
        if not report["database"]["passed"]:
            raise RuntimeError(
                "database validation failed; row counts or orphan checks did not pass"
            )
    archive_passed = report.get("archive", {}).get("passed", True)
    database_passed = report.get("database", {}).get("passed", True)
    report["passed"] = bool(archive_passed and database_passed)
    write_report(options.get("output"), report)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - CLI boundary reports everything
        argv_command = sys.argv[1] if len(sys.argv) > 1 else None
        try:
            record_failure(argv_command, error)
        except Exception:  # noqa: BLE001 - retain the primary error
            pass
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
