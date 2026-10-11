"""Structural regression tests for the staged ETL package layout."""

from pathlib import Path

from core import config as core_config
from transform import dates, values


ETL_DIR = Path(__file__).resolve().parent.parent


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
