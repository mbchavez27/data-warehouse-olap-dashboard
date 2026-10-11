#!/usr/bin/env python3
"""Safe one-command orchestration for the complete ETL pipeline."""

from __future__ import annotations

import subprocess
import sys
from typing import Callable, Optional, Sequence

import main as etl_main
from core import config
from validate import preflight


START_COMMAND = (
    "docker",
    "compose",
    "up",
    "-d",
    "--wait",
    "source_db",
    "dw_db",
)
REBUILD_COMMAND = ("bash", "db/scripts/setup_dw.sh", "--schema-only")
PHASES = ("--date", "--dims", "--facts", "--reconcile", "--check")


class UsageError(ValueError):
    """The runner arguments are invalid; callers should exit with status 2."""


class PipelineError(RuntimeError):
    """The pipeline stopped because an execution boundary failed."""


def usage() -> str:
    """Return the intentionally small command-line interface."""
    return "\n".join(
        [
            "Usage:",
            "  uv run --project etl python etl/run_pipeline.py",
            "  uv run --project etl python etl/run_pipeline.py --rebuild",
            "",
            "Default: start the databases and load only an empty warehouse.",
            "--rebuild: explicitly replace the warehouse schema before loading.",
            "The source database is never reset or modified by this command.",
        ]
    )


def parse_args(argv: Sequence[str]) -> bool:
    """Return whether an explicit warehouse rebuild was requested."""
    args = list(argv)
    if not args:
        return False
    if args == ["--rebuild"]:
        return True
    raise UsageError(usage())


def execute_pipeline(
    *,
    rebuild: bool,
    command_runner: Callable = subprocess.run,
    preflight_runner: Callable = preflight.run_preflight,
    phase_runner: Callable = etl_main.run_cli,
) -> None:
    """Start dependencies, verify safe state, then run every ETL phase."""
    command_runner(START_COMMAND, check=True, cwd=config.REPO_ROOT)
    if rebuild:
        command_runner(REBUILD_COMMAND, check=True, cwd=config.REPO_ROOT)

    try:
        preflight_runner(require_empty_facts=True)
    except preflight.PreflightError as error:
        if not rebuild and "fact rows are loaded" in str(error):
            raise PipelineError(
                f"{error}; rerun with --rebuild for an intentional clean reload"
            ) from error
        raise

    for phase in PHASES:
        exit_status = phase_runner([phase])
        if exit_status != 0:
            raise PipelineError(
                f"ETL phase {phase} failed with exit status {exit_status}"
            )


def run_cli(
    argv: Optional[Sequence[str]] = None,
    *,
    command_runner: Callable = subprocess.run,
    preflight_runner: Callable = preflight.run_preflight,
    phase_runner: Callable = etl_main.run_cli,
) -> int:
    """Run the orchestrator with stable usage and runtime exit statuses."""
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        rebuild = parse_args(args)
        execute_pipeline(
            rebuild=rebuild,
            command_runner=command_runner,
            preflight_runner=preflight_runner,
            phase_runner=phase_runner,
        )
        return 0
    except UsageError as error:
        print(error, file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001 - CLI boundary reports all failures
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run_cli())
