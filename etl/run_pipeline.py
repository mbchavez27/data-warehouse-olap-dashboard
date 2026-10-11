#!/usr/bin/env python3
"""Safe one-command orchestration for the complete ETL pipeline."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import PureWindowsPath
from typing import Callable, Mapping, Optional, Sequence

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
REBUILD_SCRIPT = ("db/scripts/setup_dw.sh", "--schema-only")
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


def _is_wsl_launcher(path: str, environ: Mapping[str, str]) -> bool:
    """True for Windows' bash.exe stubs that start WSL instead of Git Bash."""
    normalized = path.replace("/", "\\").lower()
    system_root = (environ.get("SystemRoot") or r"C:\Windows").replace("/", "\\").lower()
    return normalized.startswith(system_root.rstrip("\\") + "\\system32\\") or (
        "\\windowsapps\\" in normalized
    )


def resolve_bash(
    *,
    environ: Optional[Mapping[str, str]] = None,
    os_name: Optional[str] = None,
    which: Callable[[str], Optional[str]] = shutil.which,
    is_file: Callable[[str], bool] = os.path.isfile,
) -> str:
    """Return the Bash that runs setup_dw.sh for --rebuild.

    On Windows, CreateProcess searches System32 before PATH, so a bare "bash"
    starts the WSL launcher: Docker still answers there, but this checkout's
    Windows uv environment does not, and the schema reset dies halfway. Use
    ETL_BASH if set, else a non-WSL bash on PATH, else the Git Bash that ships
    beside git.exe.
    """
    environ = os.environ if environ is None else environ
    os_name = os.name if os_name is None else os_name
    override = environ.get("ETL_BASH")
    if override:
        if not is_file(override):
            raise PipelineError(f"ETL_BASH={override!r} is not a file")
        return override
    if os_name != "nt":
        return "bash"
    on_path = which("bash")
    if on_path and not _is_wsl_launcher(on_path, environ):
        return on_path
    git = which("git")
    if git:
        # Windows path rules, whatever the host, so the logic is testable anywhere.
        for ancestor in list(PureWindowsPath(git).parents)[:3]:
            candidate = str(ancestor / "bin" / "bash.exe")
            if is_file(candidate):
                return candidate
    raise PipelineError(
        "--rebuild runs db/scripts/setup_dw.sh and needs Git Bash on Windows; the "
        "System32 bash.exe starts WSL, which cannot see this checkout's uv "
        "environment. Install Git for Windows, or set ETL_BASH to a bash.exe."
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
    bash_resolver: Callable[[], str] = resolve_bash,
) -> None:
    """Start dependencies, verify safe state, then run every ETL phase."""
    # Resolve Bash before any side effect, so a missing Bash changes nothing.
    rebuild_command = (bash_resolver(), *REBUILD_SCRIPT) if rebuild else None
    command_runner(START_COMMAND, check=True, cwd=config.REPO_ROOT)
    if rebuild_command:
        print(f"rebuilding the warehouse schema: {' '.join(REBUILD_SCRIPT)}", flush=True)
        command_runner(rebuild_command, check=True, cwd=config.REPO_ROOT)

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
    bash_resolver: Callable[[], str] = resolve_bash,
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
            bash_resolver=bash_resolver,
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
