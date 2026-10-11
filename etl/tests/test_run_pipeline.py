"""DB-free behavior tests for the safe full-pipeline orchestrator."""

from __future__ import annotations

import subprocess

import pytest

import run_pipeline
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


def successful_boundaries(events):
    def command_runner(command, *, check, cwd):
        assert check is True
        assert cwd == config.REPO_ROOT
        events.append(("command", tuple(command)))
        return subprocess.CompletedProcess(command, 0)

    def preflight_runner(*, require_empty_facts):
        events.append(("preflight", require_empty_facts))
        return {"passed": True}

    def phase_runner(argv):
        events.append(("phase", tuple(argv)))
        return 0

    return command_runner, preflight_runner, phase_runner


@pytest.mark.parametrize("argv", [["--reset"], ["--rebuild", "extra"]])
def test_invalid_arguments_exit_two_without_side_effects(argv, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid arguments must fail before side effects")

    assert run_pipeline.run_cli(
        argv,
        command_runner=forbidden,
        preflight_runner=forbidden,
        phase_runner=forbidden,
    ) == 2
    assert "Usage:" in capsys.readouterr().err


def test_default_run_starts_databases_checks_empty_state_and_runs_exact_phase_order():
    events = []
    boundaries = successful_boundaries(events)

    assert run_pipeline.run_cli(
        [],
        command_runner=boundaries[0],
        preflight_runner=boundaries[1],
        phase_runner=boundaries[2],
    ) == 0
    assert events == [
        ("command", START_COMMAND),
        ("preflight", True),
        *(("phase", (phase,)) for phase in PHASES),
    ]


def test_default_run_never_invokes_schema_or_source_reset():
    events = []
    boundaries = successful_boundaries(events)

    assert run_pipeline.run_cli(
        [],
        command_runner=boundaries[0],
        preflight_runner=boundaries[1],
        phase_runner=boundaries[2],
    ) == 0
    commands = [event[1] for event in events if event[0] == "command"]
    assert commands == [START_COMMAND]
    assert all("setup_source" not in " ".join(command) for command in commands)
    assert all("--reset" not in command for command in commands)


def test_rebuild_invokes_only_warehouse_schema_reset_before_preflight_and_phases():
    events = []
    boundaries = successful_boundaries(events)

    assert run_pipeline.run_cli(
        ["--rebuild"],
        command_runner=boundaries[0],
        preflight_runner=boundaries[1],
        phase_runner=boundaries[2],
    ) == 0
    assert events == [
        ("command", START_COMMAND),
        ("command", REBUILD_COMMAND),
        ("preflight", True),
        *(("phase", (phase,)) for phase in PHASES),
    ]
    commands = [event[1] for event in events if event[0] == "command"]
    assert all("setup_source" not in " ".join(command) for command in commands)
    assert all("--reset" not in command for command in commands)


def test_loaded_warehouse_aborts_before_first_phase_and_suggests_rebuild(capsys):
    events = []
    command_runner, _, phase_runner = successful_boundaries(events)

    def loaded_preflight(*, require_empty_facts):
        events.append(("preflight", require_empty_facts))
        raise preflight.PreflightError("preflight: 3,036,324 fact rows are loaded")

    assert run_pipeline.run_cli(
        [],
        command_runner=command_runner,
        preflight_runner=loaded_preflight,
        phase_runner=phase_runner,
    ) == 1
    assert "--rebuild" in capsys.readouterr().err
    assert events == [("command", START_COMMAND), ("preflight", True)]


def test_docker_failure_stops_before_rebuild_preflight_and_phases():
    events = []

    def failed_command(command, *, check, cwd):
        events.append(("command", tuple(command)))
        raise subprocess.CalledProcessError(1, command)

    def forbidden(*args, **kwargs):
        raise AssertionError("later boundary ran after Docker failure")

    assert run_pipeline.run_cli(
        ["--rebuild"],
        command_runner=failed_command,
        preflight_runner=forbidden,
        phase_runner=forbidden,
    ) == 1
    assert events == [("command", START_COMMAND)]


def test_rebuild_failure_stops_before_preflight_and_phases():
    events = []

    def command_runner(command, *, check, cwd):
        events.append(("command", tuple(command)))
        if tuple(command) == REBUILD_COMMAND:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    def forbidden(*args, **kwargs):
        raise AssertionError("later boundary ran after rebuild failure")

    assert run_pipeline.run_cli(
        ["--rebuild"],
        command_runner=command_runner,
        preflight_runner=forbidden,
        phase_runner=forbidden,
    ) == 1
    assert events == [
        ("command", START_COMMAND),
        ("command", REBUILD_COMMAND),
    ]


def test_preflight_failure_stops_before_first_phase():
    events = []
    command_runner, _, phase_runner = successful_boundaries(events)

    def failed_preflight(*, require_empty_facts):
        events.append(("preflight", require_empty_facts))
        raise preflight.PreflightError("preflight: source counts mismatch")

    assert run_pipeline.run_cli(
        [],
        command_runner=command_runner,
        preflight_runner=failed_preflight,
        phase_runner=phase_runner,
    ) == 1
    assert events == [("command", START_COMMAND), ("preflight", True)]


@pytest.mark.parametrize("failed_phase", PHASES)
def test_phase_failure_stops_every_later_phase(failed_phase):
    events = []
    command_runner, preflight_runner, _ = successful_boundaries(events)

    def phase_runner(argv):
        phase = argv[0]
        events.append(("phase", tuple(argv)))
        return 1 if phase == failed_phase else 0

    assert run_pipeline.run_cli(
        [],
        command_runner=command_runner,
        preflight_runner=preflight_runner,
        phase_runner=phase_runner,
    ) == 1
    attempted = [event[1][0] for event in events if event[0] == "phase"]
    assert attempted == list(PHASES[: PHASES.index(failed_phase) + 1])
