"""Phase 0 CLI smoke tests.

Goals:
* ``lorewiki --version`` prints the package version.
* ``lorewiki --help`` lists every sub-command we promised in the dev plan.
* Sub-commands that are not yet implemented surface a clear "phase pending"
  panel and exit with code 2 (not 0).
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from lorewiki import __version__
from lorewiki.cli import app, print_phase_status


@pytest.fixture()
def runner() -> CliRunner:
    # Typer 0.12+ uses click 8.1+, which already separates stdout/stderr by
    # default. We just instantiate a plain runner here.
    return CliRunner()


def test_version_flag(runner: CliRunner) -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_help_lists_all_subcommands(runner: CliRunner) -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("init", "index", "status", "search", "ask", "mcp", "rest", "config", "topic"):
        assert cmd in result.stdout, f"sub-command {cmd!r} missing from --help"


@pytest.mark.parametrize(
    "args",
    [
        ["update"],
    ],
)
def test_phase_pending_exits_with_code_2(runner: CliRunner, args: list[str]) -> None:
    """Every still-unimplemented sub-command must signal 'pending' (exit code 2)."""
    result = runner.invoke(app, args)
    assert result.exit_code == 2, (
        f"args={args} expected exit 2, got {result.exit_code}\n"
        f"output:\n{result.output}"
    )
    assert "not yet implemented" in result.output.lower()


def test_unknown_subcommand_returns_nonzero(runner: CliRunner) -> None:
    result = runner.invoke(app, ["definitely-not-a-command"])
    assert result.exit_code != 0


def test_print_phase_status_lists_phases(capsys: pytest.CaptureFixture[str]) -> None:
    """``print_phase_status`` is a helper used by later phases; smoke-test it."""
    print_phase_status()
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    for marker in ("phase status", "bootstrap", "BM25", "RRF", "REST", "MCP"):
        assert marker.lower() in combined.lower(), f"missing marker {marker!r}"
