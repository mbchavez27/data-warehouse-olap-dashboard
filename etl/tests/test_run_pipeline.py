"""DB-free behavior tests for the safe full-pipeline orchestrator."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

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


def bash_executable() -> str:
    """Prefer Git Bash on Windows; otherwise use the Bash available in PATH."""
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if git_bash.is_file():
        return str(git_bash)
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is not available")
    return bash


def shell_path(path: Path) -> str:
    """Render a pathlib path in a form accepted by Git Bash and POSIX Bash."""
    return path.as_posix()


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
        bash_resolver=lambda: "bash",
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
        bash_resolver=lambda: "bash",
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
        bash_resolver=lambda: "bash",
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


def test_rebuild_runs_the_schema_reset_with_the_resolved_bash():
    events = []
    boundaries = successful_boundaries(events)
    git_bash = "C:/Program Files/Git/bin/bash.exe"

    assert run_pipeline.run_cli(
        ["--rebuild"],
        command_runner=boundaries[0],
        preflight_runner=boundaries[1],
        phase_runner=boundaries[2],
        bash_resolver=lambda: git_bash,
    ) == 0
    assert ("command", (git_bash, "db/scripts/setup_dw.sh", "--schema-only")) in events


def test_unresolvable_bash_stops_rebuild_before_any_command(capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("no boundary may run when Bash cannot be resolved")

    def no_bash():
        raise run_pipeline.PipelineError("--rebuild needs Bash")

    assert run_pipeline.run_cli(
        ["--rebuild"],
        command_runner=forbidden,
        preflight_runner=forbidden,
        phase_runner=forbidden,
        bash_resolver=no_bash,
    ) == 1
    assert "--rebuild needs Bash" in capsys.readouterr().err


def test_default_run_never_resolves_bash():
    events = []
    boundaries = successful_boundaries(events)

    def forbidden():
        raise AssertionError("the default run does not need Bash")

    assert run_pipeline.run_cli(
        [],
        command_runner=boundaries[0],
        preflight_runner=boundaries[1],
        phase_runner=boundaries[2],
        bash_resolver=forbidden,
    ) == 0


def fake_which(table):
    return lambda name: table.get(name)


def test_resolve_bash_uses_plain_bash_outside_windows():
    assert run_pipeline.resolve_bash(environ={}, os_name="posix", which=fake_which({})) == "bash"


def test_resolve_bash_accepts_a_non_wsl_bash_on_the_windows_path():
    git_bash = r"C:\Program Files\Git\usr\bin\bash.exe"

    assert run_pipeline.resolve_bash(
        environ={"SystemRoot": r"C:\Windows"},
        os_name="nt",
        which=fake_which({"bash": git_bash}),
        is_file=lambda path: True,
    ) == git_bash


@pytest.mark.parametrize(
    "wsl_launcher",
    [
        r"C:\Windows\System32\bash.exe",
        r"c:\windows\system32\BASH.EXE",
        r"C:\Users\User\AppData\Local\Microsoft\WindowsApps\bash.exe",
    ],
)
def test_resolve_bash_skips_the_wsl_launcher_and_finds_git_bash(wsl_launcher):
    git = r"C:\Program Files\Git\cmd\git.exe"
    expected = r"C:\Program Files\Git\bin\bash.exe"

    assert run_pipeline.resolve_bash(
        environ={"SystemRoot": r"C:\Windows"},
        os_name="nt",
        which=fake_which({"bash": wsl_launcher, "git": git}),
        is_file=lambda path: path == expected,
    ) == expected


def test_resolve_bash_honors_an_explicit_override():
    override = r"D:\tools\bash.exe"

    assert run_pipeline.resolve_bash(
        environ={"ETL_BASH": override},
        os_name="nt",
        which=fake_which({}),
        is_file=lambda path: path == override,
    ) == override


def test_resolve_bash_rejects_an_override_that_does_not_exist():
    with pytest.raises(run_pipeline.PipelineError, match="ETL_BASH"):
        run_pipeline.resolve_bash(
            environ={"ETL_BASH": r"D:\missing\bash.exe"},
            os_name="nt",
            which=fake_which({}),
            is_file=lambda path: False,
        )


def test_resolve_bash_explains_how_to_fix_a_missing_git_bash():
    with pytest.raises(run_pipeline.PipelineError, match="Git Bash.*ETL_BASH"):
        run_pipeline.resolve_bash(
            environ={"SystemRoot": r"C:\Windows"},
            os_name="nt",
            which=fake_which({"bash": r"C:\Windows\System32\bash.exe"}),
            is_file=lambda path: False,
        )


def test_shell_wrapper_has_valid_bash_syntax():
    wrapper = config.REPO_ROOT / "etl" / "run_etl.sh"

    result = subprocess.run(
        [bash_executable(), "-n", shell_path(wrapper)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ([], ["run", "--project", "etl", "python", "etl/run_pipeline.py"]),
        (
            ["--rebuild"],
            [
                "run",
                "--project",
                "etl",
                "python",
                "etl/run_pipeline.py",
                "--rebuild",
            ],
        ),
    ],
)
def test_shell_wrapper_delegates_default_and_rebuild_arguments_unchanged(
    tmp_path, arguments, expected
):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$@\" > \"$UV_ARGS_FILE\"\n"
        "exit \"$UV_EXIT_STATUS\"\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    args_file = tmp_path / "uv-args.txt"
    env = os.environ.copy()
    env["PATH"] = f"{shell_path(fake_bin)}{os.pathsep}{env.get('PATH', '')}"
    env["UV_ARGS_FILE"] = shell_path(args_file)
    env["UV_EXIT_STATUS"] = "23"

    result = subprocess.run(
        [
            bash_executable(),
            shell_path(config.REPO_ROOT / "etl" / "run_etl.sh"),
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 23
    assert args_file.read_text(encoding="utf-8").splitlines() == expected
