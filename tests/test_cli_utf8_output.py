"""Regression tests for the UTF-8 stdout fix.

Issue: on Windows PowerShell/CMD with default GBK code page, ``lorewiki
search --raw`` would emit mojibake for any CJK characters in titles /
snippets, forcing agents to fall back to direct file reads.

Fix: ``lorewiki.cli`` calls ``sys.stdout.reconfigure(encoding='utf-8')`` at
import time. These tests verify the JSON payload from a real subprocess
contains the original CJK strings byte-for-byte.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from lorewiki.config import LoreWikiConfig
from lorewiki.indexer import build_index


@pytest.fixture()
def indexed_wiki(tmp_path: Path) -> Path:
    wiki = tmp_path / "wiki"
    (wiki / "api" / "user").mkdir(parents=True)
    (wiki / "api" / "user" / "auth.md").write_text(
        "---\ntitle: 用户认证 API\nmodule: api/user\n---\n\n"
        "## 概述\n\n本接口实现 JWT 双 Token 方案,涵盖登录登出刷新流程。\n",
        encoding="utf-8",
    )
    # CLI default db_path = <wiki>/.lorewiki/index.db; honour that so the
    # subprocess can find the index without an explicit --path override.
    cfg = LoreWikiConfig(wiki_path=wiki, db_path=wiki / ".lorewiki" / "index.db")
    build_index(cfg, rebuild=True)
    return wiki


def _run_lorewiki(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    """Run the CLI as a subprocess, capture raw bytes for explicit decoding."""
    return subprocess.run(
        [sys.executable, "-m", "lorewiki", *args],
        capture_output=True,
        text=False,
        check=False,
        timeout=15,
    )


def test_search_raw_preserves_cjk_in_subprocess(indexed_wiki: Path) -> None:
    """``lorewiki search QUERY --raw`` must emit UTF-8 JSON with intact CJK.

    This is the exact regression an agent hits when calling lorewiki through
    the shell on Windows.
    """
    proc = _run_lorewiki(
        ["search", "用户认证", "--path", str(indexed_wiki), "--mode", "bm25",
         "--top-k", "3", "--raw"]
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    out_text = proc.stdout.decode("utf-8", errors="strict")
    # JSON must parse with ensure_ascii=False intact.
    payload = json.loads(out_text)
    assert payload, "expected at least one hit"
    titles = [h["title"] for h in payload]
    # The literal CJK title must round-trip — not be replaced by mojibake.
    assert any("用户认证" in t for t in titles), (
        f"expected '用户认证' in titles, got {titles!r}"
    )
    assert all("\ufffd" not in (h.get("snippet") or "") for h in payload), (
        "snippet contains UTF-8 replacement char — encoding fix failed"
    )


def test_ask_raw_preserves_cjk_in_subprocess(indexed_wiki: Path) -> None:
    """``lorewiki ask QUERY --raw`` must also emit clean UTF-8."""
    proc = _run_lorewiki(
        ["ask", "JWT 是什么", "--path", str(indexed_wiki), "--top-k", "2", "--raw"]
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    out_text = proc.stdout.decode("utf-8", errors="strict")
    payload = json.loads(out_text)
    assert payload["question"] == "JWT 是什么"
    # Fallback answer text (no LLM in tests) must include CJK source paths.
    assert "auth.md" in payload["answer"]
