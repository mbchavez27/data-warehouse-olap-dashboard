"""Append-only, report-ready evidence for every ETL CLI execution."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from core import config

RUN_LEDGER_PATH = config.REPO_ROOT / "evidence" / "etl-runs.jsonl"
REJECT_LEDGER_PATH = config.REPO_ROOT / "evidence" / "etl-rejects.json"


def utc_now() -> str:
    """Return a millisecond UTC timestamp suitable for committed evidence."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _parse_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def build_record(
    *,
    command: str,
    mode: str,
    started_at: str,
    finished_at: str,
    wall_clock_seconds: float,
    tables: Mapping[str, Mapping[str, Any]],
    rejected_rows: int,
    quarantined_rows: int,
    exit_status: int,
    error: Optional[str],
) -> Dict[str, Any]:
    """Validate and build one stable ledger record."""
    started = _parse_timestamp(started_at, "startedAt")
    finished = _parse_timestamp(finished_at, "finishedAt")
    if finished < started:
        raise ValueError("finishedAt cannot be earlier than startedAt")
    if wall_clock_seconds < 0:
        raise ValueError("wallClockSeconds cannot be negative")
    if rejected_rows < 0 or quarantined_rows < 0:
        raise ValueError("reject and quarantine counts cannot be negative")
    return {
        "schemaVersion": 1,
        "command": command,
        "mode": mode,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "wallClockSeconds": round(wall_clock_seconds, 3),
        "tables": dict(tables),
        "rejects": {
            "rejectedRows": rejected_rows,
            "quarantinedRows": quarantined_rows,
        },
        "exitStatus": exit_status,
        "error": error,
    }


def append_record(record: Mapping[str, Any], path: Optional[Path] = None) -> None:
    """Append one complete JSONL line without reading or rewriting prior runs."""
    destination = RUN_LEDGER_PATH if path is None else Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    descriptor = os.open(
        destination,
        os.O_APPEND | os.O_CREAT | os.O_WRONLY | getattr(os, "O_BINARY", 0),
        0o644,
    )
    try:
        written = os.write(descriptor, payload)
        if written != len(payload):
            raise OSError(f"short JSONL append: wrote {written} of {len(payload)} bytes")
    finally:
        os.close(descriptor)


def table_metrics(mode: str, summary: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Normalize loader-specific summaries into actual per-table writes and timings."""
    if mode == "date":
        return {
            "DIM_DATE": {
                "rowsWritten": summary["dateCount"],
                "seconds": summary["seconds"],
            }
        }
    if mode == "dims":
        return {
            table: {
                "rowsWritten": counts["inserted"] + counts["updated"],
                "seconds": counts["seconds"],
            }
            for table, counts in summary.items()
        }
    if mode == "optimize":
        # The four views build together, so each shares the phase's time.
        return {
            view: {"rowsWritten": rows, "seconds": summary["seconds"]}
            for view, rows in summary["views"].items()
        }
    if mode == "facts":
        return {
            table: {
                "rowsWritten": counts["loaded"],
                "seconds": counts["seconds"],
            }
            for table, counts in summary.items()
            if table.startswith("FACT_")
        }
    return {}


def reject_count(
    mode: str, started_at: str, path: Optional[Path] = None
) -> int:
    """Return this run's reject count, ignoring stale or unrelated mode evidence."""
    if mode not in {"dims", "facts"}:
        return 0
    source = REJECT_LEDGER_PATH if path is None else Path(path)
    try:
        report = json.loads(source.read_text(encoding="utf-8"))
        entry = report["modes"][mode]
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
        return 0
    generated = _parse_timestamp(entry.get("generatedAt"), "generatedAt")
    started = _parse_timestamp(started_at, "startedAt")
    if generated < started:
        return 0
    count = entry.get("rejectCount")
    if not isinstance(count, int) or count < 0:
        raise ValueError("rejectCount must be a nonnegative integer")
    return count
