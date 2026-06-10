"""Tests for ``lorewiki ask`` CLI integration (with LLM mocked)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lorewiki.cli import app


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def initialised_wiki(tmp_path: Path, runner: CliRunner) -> Path:
    wiki = tmp_path / "kb"
    wiki.mkdir()
    runner.invoke(app, ["init", "--path", str(wiki)])
    (wiki / "api").mkdir()
    (wiki / "api" / "auth.md").write_text(
        "---\ntitle: Auth\nmodule: api\n---\n\n# Auth\n\n"
        "## Login\n\nThe login endpoint signs and returns a JWT token pair.\n",
        encoding="utf-8",
    )
    runner.invoke(app, ["index", "--path", str(wiki)])
    return wiki


def test_ask_degrades_gracefully_without_llm(
    runner: CliRunner, initialised_wiki: Path
) -> None:
    result = runner.invoke(
        app, ["ask", "how does login work?", "--path", str(initialised_wiki)]
    )
    assert result.exit_code == 0, result.output
    assert "degraded" in result.output.lower() or "llm" in result.output.lower()
    # Source table must still surface.
    assert "auth.md" in result.output


def test_ask_raw_outputs_json(runner: CliRunner, initialised_wiki: Path) -> None:
    result = runner.invoke(
        app,
        ["ask", "how does login work?", "--path", str(initialised_wiki), "--raw"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["question"] == "how does login work?"
    assert "hits" in payload
    assert "used_llm" in payload
    # Without LLM configured, used_llm must be False.
    assert payload["used_llm"] is False


def test_ask_without_index_fails_clearly(runner: CliRunner, tmp_path: Path) -> None:
    wiki = tmp_path / "kb"
    wiki.mkdir()
    runner.invoke(app, ["init", "--path", str(wiki)])
    db = wiki / ".lorewiki" / "index.db"
    if db.exists():
        db.unlink()
    result = runner.invoke(app, ["ask", "hi", "--path", str(wiki)])
    assert result.exit_code == 1
    assert "no index found" in result.output.lower()
