"""Behavioral tests for the append-only ETL execution ledger."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _record(run_ledger, *, mode="date", exit_status=0, error=None):
    return run_ledger.build_record(
        command=f"etl/main.py --{mode}",
        mode=mode,
        started_at="2026-10-11T08:00:00.000Z",
        finished_at="2026-10-11T08:00:02.500Z",
        wall_clock_seconds=2.5,
        tables={"DIM_DATE": {"rowsWritten": 365, "seconds": 0.75}},
        rejected_rows=0,
        quarantined_rows=0,
        exit_status=exit_status,
        error=error,
    )


def test_build_record_has_report_fields_and_rejects_reversed_timestamps():
    """Dropping a required field or accepting an impossible time order must fail."""
    import run_ledger

    record = _record(run_ledger)

    assert record == {
        "schemaVersion": 1,
        "command": "etl/main.py --date",
        "mode": "date",
        "startedAt": "2026-10-11T08:00:00.000Z",
        "finishedAt": "2026-10-11T08:00:02.500Z",
        "wallClockSeconds": 2.5,
        "tables": {"DIM_DATE": {"rowsWritten": 365, "seconds": 0.75}},
        "rejects": {"rejectedRows": 0, "quarantinedRows": 0},
        "exitStatus": 0,
        "error": None,
    }

    with pytest.raises(ValueError, match="finishedAt"):
        run_ledger.build_record(
            command="etl/main.py --date",
            mode="date",
            started_at="2026-10-11T08:00:03.000Z",
            finished_at="2026-10-11T08:00:02.000Z",
            wall_clock_seconds=0,
            tables={},
            rejected_rows=0,
            quarantined_rows=0,
            exit_status=1,
            error="failed",
        )


def test_append_record_preserves_existing_lines_and_appends_one_json_object(tmp_path):
    """Replacing or corrupting an earlier run must fail this append-only test."""
    import run_ledger

    path = tmp_path / "etl-runs.jsonl"
    first = _record(run_ledger)
    second = _record(run_ledger, mode="facts", exit_status=1, error="load failed")

    run_ledger.append_record(first, path)
    first_bytes = path.read_bytes()
    run_ledger.append_record(second, path)

    assert path.read_bytes().startswith(first_bytes)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(line) for line in lines] == [first, second]


@pytest.mark.parametrize(
    ("mode", "summary", "expected"),
    [
        (
            "date",
            {"dateCount": 365, "seconds": 0.125},
            {"DIM_DATE": {"rowsWritten": 365, "seconds": 0.125}},
        ),
        (
            "dims",
            {
                "DIM_CUSTOMER": {
                    "inserted": 90,
                    "updated": 5,
                    "seconds": 1.25,
                }
            },
            {"DIM_CUSTOMER": {"rowsWritten": 95, "seconds": 1.25}},
        ),
        (
            "facts",
            {"FACT_ORDERITEM": {"loaded": 1_999_824, "seconds": 12.5}},
            {"FACT_ORDERITEM": {"rowsWritten": 1_999_824, "seconds": 12.5}},
        ),
        ("check", {"warehouse": {"passed": True}}, {}),
        ("reconcile", {"passed": True}, {}),
    ],
)
def test_table_metrics_report_real_writes_for_each_kind_of_mode(mode, summary, expected):
    """Counting source rows or inventing writes for read-only modes must fail."""
    import run_ledger

    assert run_ledger.table_metrics(mode, summary) == expected


def test_run_cli_appends_success_and_runtime_failure_with_fake_clocks(
    monkeypatch, tmp_path, capsys
):
    """Losing failed runs or using estimated timings must fail this CLI-boundary test."""
    import main as main_module

    path = tmp_path / "etl-runs.jsonl"
    times = iter([10.0, 12.75, 20.0, 20.5])
    timestamps = iter(
        [
            "2026-10-11T08:00:00.000Z",
            "2026-10-11T08:00:02.750Z",
            "2026-10-11T08:01:00.000Z",
            "2026-10-11T08:01:00.500Z",
        ]
    )
    reports = iter(
        [
            {
                "dateCount": 365,
                "minDate": "2024-09-24",
                "maxDate": "2025-09-23",
                "orderSizeSeedCount": 5,
                "seconds": 0.75,
            },
            RuntimeError("warehouse unavailable"),
        ]
    )

    def date_load():
        result = next(reports)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(main_module.load_date, "run_date_load", date_load)

    assert main_module.run_cli(
        ["--date"], ledger_path=path, clock=lambda: next(times), now=lambda: next(timestamps)
    ) == 0
    assert main_module.run_cli(
        ["--date"], ledger_path=path, clock=lambda: next(times), now=lambda: next(timestamps)
    ) == 1

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["tables"] == {
        "DIM_DATE": {"rowsWritten": 365, "seconds": 0.75}
    }
    assert records[0]["wallClockSeconds"] == 2.75
    assert records[0]["exitStatus"] == 0
    assert records[1]["tables"] == {}
    assert records[1]["wallClockSeconds"] == 0.5
    assert records[1]["exitStatus"] == 1
    assert records[1]["error"] == "RuntimeError: warehouse unavailable"
    assert "ERROR: warehouse unavailable" in capsys.readouterr().err


def test_reject_count_uses_only_the_current_modes_fresh_evidence(tmp_path):
    """Reporting another mode's or an earlier run's rejects must fail."""
    import run_ledger

    path = tmp_path / "etl-rejects.json"
    path.write_text(
        json.dumps(
            {
                "modes": {
                    "dims": {
                        "generatedAt": "2026-10-11T08:00:01.000Z",
                        "rejectCount": 3,
                    },
                    "facts": {
                        "generatedAt": "2026-10-11T07:59:00.000Z",
                        "rejectCount": 9,
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    assert run_ledger.reject_count(
        "dims", "2026-10-11T08:00:00.000Z", path
    ) == 3
    assert run_ledger.reject_count(
        "facts", "2026-10-11T08:00:00.000Z", path
    ) == 0
    assert run_ledger.reject_count(
        "date", "2026-10-11T08:00:00.000Z", path
    ) == 0
