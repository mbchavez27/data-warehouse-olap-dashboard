"""Tests for etl/config.py. No database, no network."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config


def test_load_env_parses_values_and_ignores_noise(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n"
        "\n"
        "SOURCE_DB=source_db\n"
        "SOURCE_PORT = 5433\n"
        "PASSWORD=a=b=c\n"
        "BROKENLINE\n",
        encoding="utf-8",
    )

    assert config.load_env(env_file) == {
        "SOURCE_DB": "source_db",
        "SOURCE_PORT": "5433",
        "PASSWORD": "a=b=c",
    }


def test_load_env_missing_file_yields_empty(tmp_path):
    assert config.load_env(tmp_path / ".env") == {}


def test_dsns_use_defaults_when_no_env_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")

    assert config.source_dsn() == (
        "host=localhost port=5433 dbname=source_db "
        "user=postgres password=postgres"
    )
    assert config.dw_dsn() == (
        "host=localhost port=5434 dbname=dw_db user=postgres password=postgres"
    )


def test_explicit_env_wins_over_file_and_defaults(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("SOURCE_PORT=9999\n", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", env_file)

    dsn = config.source_dsn({"SOURCE_PORT": "5433", "SOURCE_PASSWORD": "s3cr=t"})
    assert "port=5433" in dsn
    assert "password=s3cr=t" in dsn


def test_expected_source_counts_match_accepted_dataset():
    assert config.EXPECTED_SOURCE_COUNTS == {
        "Couriers": 3,
        "Riders": 100,
        "Users": 100000,
        "Products": 10000,
        "Orders": 1000000,
        "OrderItems": 1999824,
    }
    assert sum(config.EXPECTED_SOURCE_COUNTS.values()) == 3109927
