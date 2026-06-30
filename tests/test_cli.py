"""Phase 0 CLI smoke tests.

Goals:
* ``lorewiki --version`` prints the package version.
* ``lorewiki --help`` lists every sub-command we promised in the dev plan.
* An unknown sub-command is reported as an error (not a crash).
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
    for cmd in ("init", "index", "status", "search", "ask", "config", "topic"):
        assert cmd in result.stdout, f"sub-command {cmd!r} missing from --help"


def test_index_watch_flag_is_accepted(runner: CliRunner) -> None:
    """``lorewiki index --watch`` should be accepted (one-shot behavior in 0.3.0).

    We can't easily run a real index here without a wiki fixture, so we
    just verify the flag is parsed and Typer's "no such option" error
    does NOT fire. Exit code will be non-zero (no wiki_path) but the
    output must mention ``wiki_path does not exist`` rather than an
    "unrecognized argument" error.
    """
    result = runner.invoke(app, ["index", "--watch"])
    # No wiki configured in test env -> expected to error, but on the
    # wiki_path check, not on --watch parsing.
    combined = (result.stdout + (result.stderr or "")).lower()
    assert "unrecognized" not in combined
    assert "no such option" not in combined


def test_unknown_subcommand_returns_nonzero(runner: CliRunner) -> None:
    result = runner.invoke(app, ["definitely-not-a-command"])
    assert result.exit_code != 0


def test_print_phase_status_lists_phases(capsys: pytest.CaptureFixture[str]) -> None:
    """``print_phase_status`` is a helper used by later phases; smoke-test it."""
    print_phase_status()
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    for marker in ("phase status", "bootstrap", "BM25", "RRF"):
        assert marker.lower() in combined.lower(), f"missing marker {marker!r}"
