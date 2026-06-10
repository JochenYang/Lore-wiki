"""End-to-end CLI tests for phase-1 commands (init / index / status / search / config)."""

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
def fresh_wiki(tmp_path: Path) -> Path:
    """An empty directory used as a wiki root for init / index / search tests."""
    root = tmp_path / "wiki"
    root.mkdir()
    return root


def test_init_creates_config_and_starter_doc(runner: CliRunner, fresh_wiki: Path) -> None:
    result = runner.invoke(app, ["init", "--path", str(fresh_wiki)])
    assert result.exit_code == 0, result.output
    assert (fresh_wiki / ".lorewiki" / "config.toml").exists()
    assert (fresh_wiki / "index.md").exists()
    body = (fresh_wiki / "index.md").read_text(encoding="utf-8")
    assert "title:" in body


def test_init_refuses_to_overwrite_without_force(runner: CliRunner, fresh_wiki: Path) -> None:
    runner.invoke(app, ["init", "--path", str(fresh_wiki)])
    result = runner.invoke(app, ["init", "--path", str(fresh_wiki)])
    assert result.exit_code == 1
    assert "already initialised" in result.output.lower()


def test_init_then_index_then_search(runner: CliRunner, tmp_path: Path) -> None:
    wiki = tmp_path / "kb"
    wiki.mkdir()
    # init
    init_res = runner.invoke(app, ["init", "--path", str(wiki)])
    assert init_res.exit_code == 0, init_res.output

    # add a richer doc so we can grep for it
    (wiki / "api").mkdir()
    (wiki / "api" / "auth.md").write_text(
        "---\ntitle: Authentication\nmodule: api\n---\n\n"
        "# Authentication\n\n## JWT\n\nUse JWT tokens with rotation.\n",
        encoding="utf-8",
    )

    # index
    idx_res = runner.invoke(app, ["index", "--path", str(wiki), "--rebuild"])
    assert idx_res.exit_code == 0, idx_res.output
    assert "Chunks written" in idx_res.output

    # status
    status_res = runner.invoke(app, ["status", "--path", str(wiki)])
    assert status_res.exit_code == 0, status_res.output
    assert "Documents" in status_res.output
    assert "Chunks" in status_res.output

    # search (text mode)
    search_res = runner.invoke(app, ["search", "JWT", "--path", str(wiki), "--mode", "bm25"])
    assert search_res.exit_code == 0, search_res.output
    assert "auth.md" in search_res.output

    # search --raw (json mode)
    raw_res = runner.invoke(
        app, ["search", "JWT", "--path", str(wiki), "--mode", "bm25", "--raw", "--top-k", "2"]
    )
    assert raw_res.exit_code == 0, raw_res.output
    payload = json.loads(raw_res.output)
    assert isinstance(payload, list)
    assert all("chunk_id" in r for r in payload)


def test_search_vector_mode_falls_back_with_notice(runner: CliRunner, tmp_path: Path) -> None:
    """Vector retrieval is phase 6; CLI must degrade with a clear notice."""
    wiki = tmp_path / "kb"
    wiki.mkdir()
    runner.invoke(app, ["init", "--path", str(wiki)])
    runner.invoke(app, ["index", "--path", str(wiki)])
    result = runner.invoke(app, ["search", "wiki", "--path", str(wiki), "--mode", "vector"])
    assert result.exit_code == 0
    assert "vector retrieval is scheduled" in result.output.lower()


def test_status_without_index_fails_clearly(runner: CliRunner, tmp_path: Path) -> None:
    wiki = tmp_path / "kb"
    wiki.mkdir()
    runner.invoke(app, ["init", "--path", str(wiki)])
    # delete the empty db that init implicitly created… actually init doesn't
    # touch the db file, only the config. So status should still fail.
    db = wiki / ".lorewiki" / "index.db"
    if db.exists():
        db.unlink()
    result = runner.invoke(app, ["status", "--path", str(wiki)])
    assert result.exit_code == 1
    assert "no index found" in result.output.lower()


def test_config_list_get_set_round_trip(runner: CliRunner, tmp_path: Path) -> None:
    wiki = tmp_path / "kb"
    wiki.mkdir()
    runner.invoke(app, ["init", "--path", str(wiki)])

    list_res = runner.invoke(app, ["config", "list", "--path", str(wiki)])
    assert list_res.exit_code == 0
    assert "retrieval_mode" in list_res.output

    get_res = runner.invoke(app, ["config", "get", "retrieval_mode", "--path", str(wiki)])
    assert get_res.exit_code == 0
    assert get_res.output.strip() == "mix"

    set_res = runner.invoke(
        app, ["config", "set", "retrieval_mode", '"bm25"', "--path", str(wiki)]
    )
    assert set_res.exit_code == 0, set_res.output

    after = runner.invoke(app, ["config", "get", "retrieval_mode", "--path", str(wiki)])
    assert after.exit_code == 0
    assert after.output.strip() == "bm25"


def test_config_get_unknown_key_returns_error(runner: CliRunner, tmp_path: Path) -> None:
    wiki = tmp_path / "kb"
    wiki.mkdir()
    runner.invoke(app, ["init", "--path", str(wiki)])
    result = runner.invoke(app, ["config", "get", "no_such_key", "--path", str(wiki)])
    assert result.exit_code == 1
    assert "unknown key" in result.output.lower()
