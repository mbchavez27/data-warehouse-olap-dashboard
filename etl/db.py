"""Database connection helpers. Fail-fast with remediation pointers."""

from __future__ import annotations

from typing import Dict, Optional

import psycopg

import config


def connect_source(env: Optional[Dict[str, str]] = None):
    """Open source_db, or raise naming the setup script that fixes it."""
    try:
        return psycopg.connect(config.source_dsn(env))
    except psycopg.OperationalError as exc:
        raise ConnectionError(
            "source_db unreachable. Run: ./db/scripts/setup_source.sh"
        ) from exc


def connect_warehouse(env: Optional[Dict[str, str]] = None):
    """Open dw_db, or raise naming the setup script that fixes it."""
    try:
        return psycopg.connect(config.dw_dsn(env))
    except psycopg.OperationalError as exc:
        raise ConnectionError(
            "dw_db unreachable. Run: ./db/scripts/setup_dw.sh"
        ) from exc
