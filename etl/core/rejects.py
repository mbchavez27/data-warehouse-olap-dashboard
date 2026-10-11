"""Reject ledger shared by every ETL load mode.

evidence/etl-rejects.json holds one entry per mode (dims, facts, ...). Each
load rewrites its own entry on every run, success or abort, so the file always
shows the latest result; an empty rejects list is the proof of a clean load.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import config

LEDGER_PATH = config.REPO_ROOT / "evidence" / "etl-rejects.json"
MAX_LISTED = 50  # keep the evidence file readable; counts stay complete


class Ledger:
    def __init__(self) -> None:
        self.count = 0
        self.items: List[Dict[str, Any]] = []
        self._reasons: Counter = Counter()

    def add(self, table: str, source_id: Any, reason: str) -> None:
        self.count += 1
        self._reasons[f"{table}: {reason.split(':')[0]}"] += 1
        if len(self.items) < MAX_LISTED:
            self.items.append({"table": table, "sourceId": source_id, "reason": reason})

    def by_reason(self) -> Dict[str, int]:
        return dict(self._reasons)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def write(mode: str, ledger: Ledger, path: Optional[Path] = None) -> None:
    """Replace this mode's entry; other modes' entries are kept."""
    path = LEDGER_PATH if path is None else path
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        report = {}
    report["schemaVersion"] = 1
    modes = report.setdefault("modes", {})
    modes[mode] = {
        "generatedAt": _now(),
        "rejectCount": ledger.count,
        "byReason": ledger.by_reason(),
        "rejects": ledger.items,
        "passed": ledger.count == 0,
    }
    report["passed"] = all(entry["passed"] for entry in modes.values())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
