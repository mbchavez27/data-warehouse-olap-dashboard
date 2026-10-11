"""Behavioral tests for post-load source-to-warehouse reconciliation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from validate import reconcile


SOURCE_SNAPSHOT = {
    "orders": 1_000_000,
    "orderItems": 1_999_824,
    "riders": 100,
    "users": 100_000,
    "products": 10_000,
    "distinctGeographies": 100_000,
    "dateCount": 365,
    "units": 10_999_917,
}

WAREHOUSE_SNAPSHOT = {
    "factOrderDelivery": 1_000_000,
    "factOrderItem": 1_999_824,
    "factRiderDaily": 36_500,
    "dimDate": 365,
    "dimRider": 100,
    "dimGeography": 100_000,
    "dimCustomer": 100_000,
    "dimProduct": 10_000,
    "dimOrderSize": 5,
    "factOrderDeliveryUnits": 10_999_917,
    "factOrderItemUnits": 10_999_917,
    "factRiderDailyUnits": 10_999_917,
    "unknownSeedRows": {
        "DIM_RIDER": 1,
        "DIM_GEOGRAPHY": 1,
        "DIM_ORDERSIZE": 1,
        "DIM_CUSTOMER": 1,
        "DIM_PRODUCT": 1,
    },
    "unknownFactReferences": {
        "DIM_RIDER": 0,
        "DIM_GEOGRAPHY": 0,
        "DIM_ORDERSIZE": 0,
        "DIM_CUSTOMER": 0,
        "DIM_PRODUCT": 0,
    },
}

EMPTY_REJECTS = {
    "schemaVersion": 1,
    "modes": {
        "dims": {"rejectCount": 0, "passed": True},
        "facts": {"rejectCount": 0, "passed": True},
    },
    "passed": True,
}


class ScriptedCursor:
    def __init__(self, responses, statements):
        self._responses = list(responses)
        self._statements = statements
        self._current = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement):
        self._statements.append(statement)
        self._current = self._responses.pop(0)

    def fetchone(self):
        return self._current

    def fetchall(self):
        return self._current


class ScriptedConnection:
    def __init__(self, responses):
        self.statements = []
        self.cursor_instance = ScriptedCursor(responses, self.statements)
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True


def test_build_report_passes_every_required_tie_out():
    """A missing or incorrectly wired count/unit check must fail this test."""
    report = reconcile.build_report(
        SOURCE_SNAPSHOT,
        WAREHOUSE_SNAPSHOT,
        EMPTY_REJECTS,
        generated_at="2026-10-11T06:00:00.000Z",
    )

    assert report["schemaVersion"] == 1
    assert report["command"] == "reconcile"
    assert report["generatedAt"] == "2026-10-11T06:00:00.000Z"
    assert report["passed"] is True
    assert report["failedChecks"] == []
    assert report["checks"]["factOrderDeliveryCount"] == {
        "expected": 1_000_000,
        "actual": 1_000_000,
        "passed": True,
    }
    assert report["checks"]["factRiderDailyCount"] == {
        "expected": 36_500,
        "actual": 36_500,
        "passed": True,
    }
    assert report["checks"]["dimGeographyCount"]["passed"] is True
    assert report["checks"]["factOrderItemUnits"]["passed"] is True
    assert report["checks"]["unknownSeedRows"]["passed"] is True
    assert report["checks"]["unknownFactReferences"]["passed"] is True
    assert report["checks"]["rejectCount"] == {
        "expected": 0,
        "actual": 0,
        "passed": True,
    }


def test_build_report_names_a_single_failed_check():
    """Changing one warehouse total must produce one explicit failed check."""
    warehouse = dict(WAREHOUSE_SNAPSHOT, factOrderItem=1_999_823)

    report = reconcile.build_report(
        SOURCE_SNAPSHOT,
        warehouse,
        EMPTY_REJECTS,
        generated_at="2026-10-11T06:00:00.000Z",
    )

    assert report["passed"] is False
    assert report["failedChecks"] == ["factOrderItemCount"]
    assert report["checks"]["factOrderItemCount"] == {
        "expected": 1_999_824,
        "actual": 1_999_823,
        "passed": False,
    }


def test_rider_daily_expectation_comes_from_source_dates_not_warehouse_dates():
    """A consistently truncated date dimension and snapshot must fail both checks."""
    warehouse = dict(WAREHOUSE_SNAPSHOT, dimDate=364, factRiderDaily=36_400)

    report = reconcile.build_report(
        SOURCE_SNAPSHOT,
        warehouse,
        EMPTY_REJECTS,
        generated_at="2026-10-11T06:00:00.000Z",
    )

    assert report["checks"]["dimDateCount"]["passed"] is False
    assert report["checks"]["factRiderDailyCount"] == {
        "expected": 36_500,
        "actual": 36_400,
        "passed": False,
    }


def test_build_report_counts_rejects_across_modes():
    """A nonempty reject mode must prevent a passing reconciliation."""
    rejects = {
        "schemaVersion": 1,
        "modes": {
            "dims": {"rejectCount": 0, "passed": True},
            "facts": {"rejectCount": 2, "passed": False},
        },
        "passed": False,
    }

    report = reconcile.build_report(
        SOURCE_SNAPSHOT,
        WAREHOUSE_SNAPSHOT,
        rejects,
        generated_at="2026-10-11T06:00:00.000Z",
    )

    assert report["passed"] is False
    assert report["failedChecks"] == ["rejectCount"]
    assert report["checks"]["rejectCount"]["actual"] == 2


def test_write_evidence_persists_pass_and_per_check_results(tmp_path):
    """Dropping top-level or per-check verdicts must break the evidence contract."""
    output = tmp_path / "nested" / "etl-reconciliation.json"
    report = reconcile.build_report(
        SOURCE_SNAPSHOT,
        WAREHOUSE_SNAPSHOT,
        EMPTY_REJECTS,
        generated_at="2026-10-11T06:00:00.000Z",
    )

    reconcile.write_evidence(report, output)

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["passed"] is True
    assert saved["checks"]["dimDateCount"]["passed"] is True
    assert saved["source"]["orders"] == 1_000_000
    assert saved["warehouse"]["factOrderDelivery"] == 1_000_000


def test_assert_reconciled_names_every_failed_check():
    """A false report must raise with the precise failed-check names."""
    warehouse = dict(
        WAREHOUSE_SNAPSHOT,
        factOrderDelivery=999_999,
        unknownFactReferences=dict(
            WAREHOUSE_SNAPSHOT["unknownFactReferences"], DIM_RIDER=1
        ),
    )
    report = reconcile.build_report(
        SOURCE_SNAPSHOT,
        warehouse,
        EMPTY_REJECTS,
        generated_at="2026-10-11T06:00:00.000Z",
    )

    with pytest.raises(
        reconcile.ReconciliationError,
        match="factOrderDeliveryCount, unknownFactReferences",
    ):
        reconcile.assert_reconciled(report)


def test_run_reconciliation_uses_loaded_preflight_writes_then_fails(
    monkeypatch, tmp_path
):
    """A mismatch must still leave a diagnostic JSON file and exit by exception."""
    events = []
    output = tmp_path / "failed.json"
    env = {"SOURCE_HOST": "source.test", "DW_HOST": "warehouse.test"}
    warehouse = dict(WAREHOUSE_SNAPSHOT, dimProduct=9_999)

    monkeypatch.setattr(
        reconcile.preflight,
        "run_preflight",
        lambda **kwargs: events.append(("preflight", kwargs)),
    )
    monkeypatch.setattr(
        reconcile,
        "_collect_live_snapshots",
        lambda env=None: (events.append(("collect", env)) or (SOURCE_SNAPSHOT, warehouse)),
    )
    monkeypatch.setattr(reconcile, "read_reject_ledger", lambda path=None: EMPTY_REJECTS)

    with pytest.raises(reconcile.ReconciliationError, match="dimProductCount"):
        reconcile.run_reconciliation(
            output_path=output,
            env=env,
            generated_at="2026-10-11T06:00:00.000Z",
        )

    assert events == [
        ("preflight", {"env": env, "require_empty_facts": False}),
        ("collect", env),
    ]
    assert json.loads(output.read_text(encoding="utf-8"))["passed"] is False


def test_collect_live_snapshots_uses_only_selects_and_closes_connections(monkeypatch):
    """A write query, incomplete snapshot, or leaked connection must fail this test."""
    source = ScriptedConnection(
        [
            (1_000_000, 1_999_824, 100, 100_000, 10_000, 100_000, 10_999_917),
            [("09/24/2024",), ("2025-09-23",)],
        ]
    )
    warehouse = ScriptedConnection(
        [
            (
                1_000_000,
                1_999_824,
                36_500,
                365,
                100,
                100_000,
                100_000,
                10_000,
                5,
                10_999_917,
                10_999_917,
                10_999_917,
            ),
            (1, 1, 1, 1, 1),
            (0, 0, 0, 0, 0),
        ]
    )
    monkeypatch.setattr(reconcile.db, "connect_source", lambda env=None: source)
    monkeypatch.setattr(reconcile.db, "connect_warehouse", lambda env=None: warehouse)

    actual_source, actual_warehouse = reconcile._collect_live_snapshots()

    assert actual_source == SOURCE_SNAPSHOT
    assert actual_warehouse == WAREHOUSE_SNAPSHOT
    assert source.closed is True
    assert warehouse.closed is True
    assert all(
        statement.lstrip().upper().startswith("SELECT")
        for statement in source.statements + warehouse.statements
    )


def test_main_reconcile_mode_supports_default_and_explicit_output(monkeypatch, capsys):
    """Removing either documented CLI form must fail this public-interface test."""
    import main as main_module

    calls = []

    def fake_run(output_path=None):
        calls.append(output_path)
        return {"passed": True, "checks": {"one": {"passed": True}}}

    monkeypatch.setattr(main_module.reconcile, "run_reconciliation", fake_run)

    main_module.main(["--reconcile"])
    main_module.main(["--reconcile", "--output", "custom.json"])

    assert calls == [None, Path("custom.json")]
    assert capsys.readouterr().out.count("reconciliation passed: 1/1 checks") == 2


@pytest.mark.parametrize(
    "argv",
    [
        ["--reconcile", "--output"],
        ["--reconcile", "custom.json"],
        ["--reconcile", "--unknown", "custom.json"],
    ],
)
def test_main_reconcile_mode_rejects_malformed_arguments(argv, tmp_path):
    """Malformed reconcile arguments must remain usage errors (exit 2)."""
    import main as main_module

    assert main_module.run_cli(argv, ledger_path=tmp_path / "runs.jsonl") == 2
