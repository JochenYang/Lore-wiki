"""Tests for `lorewiki inject` — auto-inject wiki context into LLM sessions.

Covers the three internal helpers (_extract_keywords /
_search_wiki_for_keywords / _format_context_block) and the CLI command
end-to-end (init → index → inject), mirroring the phase-1 CLI test style.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lorewiki.cli import app
from lorewiki.cli.helpers import resolve_config
from lorewiki.cli.inject_cmd import (
    _extract_keywords,
    _format_context_block,
    _search_wiki_for_keywords,
)


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# _extract_keywords
# ---------------------------------------------------------------------------


def test_extract_keywords_finds_wx_api_calls(tmp_path: Path) -> None:
    """`wx.login` / `wx.request` calls should be extracted with the `wx.` prefix."""
    (tmp_path / "app.js").write_text(
        "wx.login({ success: () => {} });\n"
        "wx.request({ url: '/api' });\n"
        "console.log('done');\n",
        encoding="utf-8",
    )
    kws = _extract_keywords(tmp_path, max_keywords=10)
    assert "wx.login" in kws
    assert "wx.request" in kws
    # `console` is a stop word and must not leak through.
    assert "console" not in kws


def test_extract_keywords_imports_and_skips_vendor_dirs(tmp_path: Path) -> None:
    """Imports contribute module names; node_modules / venvs are skipped."""
    (tmp_path / "main.ts").write_text(
        "import React from 'react';\n"
        "import { useState } from 'react';\n"
        "from fastapi import FastAPI\n",
        encoding="utf-8",
    )
    # Files under node_modules / .venv should be ignored even if they match.
    nm = tmp_path / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("wx.login();\n", encoding="utf-8")

    kws = _extract_keywords(tmp_path, max_keywords=10)
    assert "react" in kws
    assert "fastapi" in kws
    # The wx.login inside node_modules must NOT be picked up.
    assert "wx.login" not in kws


def test_extract_keywords_empty_dir(tmp_path: Path) -> None:
    """An empty project yields no keywords."""
    assert _extract_keywords(tmp_path) == []


# ---------------------------------------------------------------------------
# _search_wiki_for_keywords
# ---------------------------------------------------------------------------


def _bootstrap_wiki(runner: CliRunner, wiki: Path) -> None:
    """init + index a wiki that contains one WeChat mini-program doc."""
    runner.invoke(app, ["init", "--path", str(wiki)])
    (wiki / "api").mkdir(exist_ok=True)
    (wiki / "api" / "wechat.md").write_text(
        "---\n"
        "title: WeChat Login\n"
        "module: api\n"
        "type: guide\n"
        "---\n\n"
        "# WeChat Login\n\n"
        "Use wx.login to obtain a login code, then exchange it for a session.\n",
        encoding="utf-8",
    )
    res = runner.invoke(app, ["index", "--path", str(wiki), "--rebuild"])
    assert res.exit_code == 0, res.output


def test_search_wiki_for_keywords_finds_doc(runner: CliRunner, tmp_path: Path) -> None:
    """A `wx.login` keyword should match the WeChat doc and return a summary."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    _bootstrap_wiki(runner, wiki)

    cfg = resolve_config(str(wiki))
    docs = _search_wiki_for_keywords(cfg, ["wx.login"])
    assert len(docs) >= 1
    doc = docs[0]
    assert doc["doc_path"].endswith("wechat.md")
    assert "WeChat" in doc["title"]
    # Enrichment from doc_summaries table.
    assert "summary" in doc
    assert doc["doc_type"] == "guide"


def test_search_wiki_for_keywords_empty_keywords(runner: CliRunner, tmp_path: Path) -> None:
    """No keywords → no docs and no DB access."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    _bootstrap_wiki(runner, wiki)
    cfg = resolve_config(str(wiki))
    assert _search_wiki_for_keywords(cfg, []) == []


# ---------------------------------------------------------------------------
# _format_context_block
# ---------------------------------------------------------------------------


def test_format_context_block_with_docs() -> None:
    docs = [
        {
            "doc_path": "api/auth.md",
            "title": "Auth",
            "module": "api",
            "matched_keyword": "wx.login",
            "score": 1.5,
            "summary": "Short summary." * 30,  # > 200 chars to test truncation
            "doc_type": "guide",
        }
    ]
    out = _format_context_block(docs, ["wx.login", "react"])
    assert "## Knowledge Base Context (auto-injected)" in out
    assert "wx.login" in out
    assert "**Auth** [guide]" in out
    assert "api/auth.md" in out
    assert "lorewiki show" in out
    # Summary is truncated to 200 chars: the tail past char 200 must not leak.
    assert len(docs[0]["summary"]) > 200
    assert docs[0]["summary"][200:] not in out


def test_format_context_block_no_docs() -> None:
    out = _format_context_block([], ["wx.login"])
    assert "No relevant docs found" in out


# ---------------------------------------------------------------------------
# inject command (end-to-end)
# ---------------------------------------------------------------------------


def test_inject_command_markdown(runner: CliRunner, tmp_path: Path) -> None:
    """End-to-end: init+index wiki, scan a project, get a markdown context block."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    _bootstrap_wiki(runner, wiki)

    project = tmp_path / "project"
    project.mkdir()
    (project / "app.js").write_text(
        "wx.login({ success: () => console.log('ok') });\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["inject", "--project", str(project), "--path", str(wiki)],
    )
    assert result.exit_code == 0, result.output
    assert "Knowledge Base Context" in result.output
    assert "wx.login" in result.output
    assert "wechat.md" in result.output


def test_inject_command_json(runner: CliRunner, tmp_path: Path) -> None:
    """JSON output is parseable and contains keywords + matched_docs."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    _bootstrap_wiki(runner, wiki)

    project = tmp_path / "project"
    project.mkdir()
    (project / "app.js").write_text("wx.login({});\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["inject", "--project", str(project), "--path", str(wiki), "--format", "json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "wx.login" in payload["keywords"]
    assert isinstance(payload["matched_docs"], list)
    assert any(d["doc_path"].endswith("wechat.md") for d in payload["matched_docs"])


def test_inject_command_missing_project_dir(runner: CliRunner, tmp_path: Path) -> None:
    """A non-existent project dir exits 1 with a clear message."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    _bootstrap_wiki(runner, wiki)

    result = runner.invoke(
        app,
        ["inject", "--project", str(tmp_path / "nope"), "--path", str(wiki)],
    )
    assert result.exit_code == 1
    assert "Project directory not found" in result.output


def test_inject_command_no_index(runner: CliRunner, tmp_path: Path) -> None:
    """Without an indexed DB, inject exits 2 (no wiki index found)."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    runner.invoke(app, ["init", "--path", str(wiki)])
    # Deliberately skip `index` so the db doesn't exist.

    project = tmp_path / "project"
    project.mkdir()
    (project / "app.js").write_text("wx.login();\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["inject", "--project", str(project), "--path", str(wiki)],
    )
    assert result.exit_code == 2
    assert "No wiki index found" in result.output


def test_inject_command_no_keywords(runner: CliRunner, tmp_path: Path) -> None:
    """A project with no code files exits 0 with a 'no keywords' notice."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    _bootstrap_wiki(runner, wiki)

    project = tmp_path / "empty_project"
    project.mkdir()

    result = runner.invoke(
        app,
        ["inject", "--project", str(project), "--path", str(wiki)],
    )
    assert result.exit_code == 0
    assert "No keywords extracted" in result.output
