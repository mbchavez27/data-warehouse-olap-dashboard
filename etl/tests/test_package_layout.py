"""Structural regression tests for the staged ETL package layout."""

import ast
import importlib
import re
from pathlib import Path

from core import config as core_config
from transform import dates, values


ETL_DIR = Path(__file__).resolve().parent.parent
REQUIRED_MODULES = (
    "extract.queries",
    "load.date",
    "load.dimensions",
    "load.facts",
    "load.summaries",
    "validate.preflight",
    "validate.reconcile",
)
OBSOLETE_STAGE_FILES = (
    "load_date.py",
    "load_dims.py",
    "load_facts.py",
    "preflight.py",
    "reconcile.py",
)
SOURCE_QUERY_NAMES = (
    "DATE_SOURCE_SQL",
    "RIDER_SOURCE_SQL",
    "GEOGRAPHY_SOURCE_SQL",
    "CUSTOMER_SOURCE_SQL",
    "PRODUCT_SOURCE_SQL",
    "DELIVERY_SOURCE_SQL",
    "ITEM_SOURCE_SQL",
    "CUSTOMER_ADDRESS_SOURCE_SQL",
)
WRITE_KEYWORDS = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE)\b", re.IGNORECASE
)


def test_core_config_keeps_repository_root_after_move():
    assert core_config.REPO_ROOT == Path(__file__).resolve().parents[2]
    assert (
        core_config.REPO_ROOT / "db" / "dw" / "init" / "01_dw_schema.sql"
    ).is_file()


def test_core_and_transform_modules_import_from_new_paths():
    assert Path(core_config.__file__).as_posix().endswith("etl/core/config.py")
    assert Path(dates.__file__).as_posix().endswith("etl/transform/dates.py")
    assert Path(values.__file__).as_posix().endswith("etl/transform/values.py")


def test_obsolete_core_and_transform_flat_modules_are_absent():
    obsolete = (
        "config.py",
        "db.py",
        "dates.py",
        "rejects.py",
        "run_ledger.py",
        "transform.py",
    )
    assert [name for name in obsolete if (ETL_DIR / name).exists()] == []


def _import_roots(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_final_stage_modules_import_and_obsolete_flat_files_are_absent():
    imported = {name: importlib.import_module(name) for name in REQUIRED_MODULES}

    assert set(imported) == set(REQUIRED_MODULES)
    assert [name for name in OBSOLETE_STAGE_FILES if (ETL_DIR / name).exists()] == []


def test_packages_enforce_one_way_dependency_boundaries():
    forbidden = {
        "core": {"extract", "transform", "load", "validate"},
        "extract": {"load", "psycopg"},
        "transform": {"psycopg", "core", "extract", "load", "validate"},
        "validate": {"load"},
    }

    violations = {}
    for package, denied in forbidden.items():
        for path in sorted((ETL_DIR / package).glob("*.py")):
            found = _import_roots(path) & denied
            if found:
                violations[path.relative_to(ETL_DIR).as_posix()] = sorted(found)

    assert violations == {}


def test_extraction_queries_are_read_only_and_owned_by_loaders():
    queries = importlib.import_module("extract.queries")

    for name in SOURCE_QUERY_NAMES:
        statement = getattr(queries, name)
        assert statement.lstrip().upper().startswith("SELECT")
        assert WRITE_KEYWORDS.search(statement) is None

    for module_name in ("load.date", "load.dimensions", "load.facts"):
        loader = importlib.import_module(module_name)
        assert loader.queries is queries
