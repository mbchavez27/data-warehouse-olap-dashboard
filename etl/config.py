"""Connection configuration for the ETL pipeline.

Single owner of credentials: nothing else in etl/ hardcodes hosts, ports,
or passwords. load_env mirrors the importer semantics (blank/# skipped,
first-= split, no quote stripping).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"

# Mirror of importer TABLES expectations (db/source/importer/cli.py).
EXPECTED_SOURCE_COUNTS = {
    "Couriers": 3,
    "Riders": 100,
    "Users": 100000,
    "Products": 10000,
    "Orders": 1000000,
    "OrderItems": 1999824,
}

_DEFAULTS = {
    "SOURCE_HOST": "localhost",
    "SOURCE_PORT": "5433",
    "SOURCE_DB": "source_db",
    "SOURCE_USER": "postgres",
    "SOURCE_PASSWORD": "postgres",
    "DW_HOST": "localhost",
    "DW_PORT": "5434",
    "DW_DB": "dw_db",
    "DW_USER": "postgres",
    "DW_PASSWORD": "postgres",
}


def load_env(path: Path = ENV_FILE) -> Dict[str, str]:
    """Parse KEY=value lines; a missing file yields {} (defaults apply)."""
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


def _merged(env: Optional[Dict[str, str]]) -> Dict[str, str]:
    merged = dict(_DEFAULTS)
    merged.update(load_env())
    if env:
        merged.update(env)
    return merged


def _dsn(settings: Dict[str, str], prefix: str) -> str:
    # Keyword form: values with special characters need no URL-encoding.
    return (
        f"host={settings[prefix + '_HOST']} port={settings[prefix + '_PORT']} "
        f"dbname={settings[prefix + '_DB']} user={settings[prefix + '_USER']} "
        f"password={settings[prefix + '_PASSWORD']}"
    )


def source_dsn(env: Optional[Dict[str, str]] = None) -> str:
    """Psycopg DSN for source_db. Explicit env wins, then .env, then defaults."""
    return _dsn(_merged(env), "SOURCE")


def dw_dsn(env: Optional[Dict[str, str]] = None) -> str:
    """Psycopg DSN for dw_db. Explicit env wins, then .env, then defaults."""
    return _dsn(_merged(env), "DW")
