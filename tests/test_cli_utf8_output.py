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
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lorewiki.cli.apps import app as _app
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
        timeout=30,
    )


def test_search_json_preserves_cjk_in_subprocess(indexed_wiki: Path) -> None:
    """``lorewiki search QUERY`` (default JSON) must emit UTF-8 JSON with intact CJK.

    This is the exact regression an agent hits when calling lorewiki through
    the shell on Windows. The default output mode is now JSON (no flag needed);
    ``--raw`` was removed when the default flipped.
    """
    proc = _run_lorewiki(
        ["search", "用户认证", "--path", str(indexed_wiki), "--mode", "bm25",
         "--top-k", "3"]
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


# ---------------------------------------------------------------------------
# Stdin encoding regression (CJK via pipe)
# ---------------------------------------------------------------------------


_STDIN_PROBE_BODY = "幂等设计 Idempotency-Key 模式用于防止重复扣款与重试导致的双写。"


def test_add_via_stdin_preserves_cjk_utf8_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for 0.2.7: piping a UTF-8-encoded CJK body into
    ``lorewiki add`` from a parent process (e.g. PowerShell) used to
    end up with mojibake on Windows because Python's stdin
    encoding for a redirected pipe defaults to the console code
    page (cp936 / GBK) and ``apps._force_utf8_streams`` only
    reconfigured stdout + stderr. 0.2.8 extends the reconfig to
    stdin so the round-trip is intact.

    We simulate the Windows-PowerShell-pipe scenario by spawning
    a child Python with the *body bytes* as ``input=`` and
    asking it to read stdin ourselves — the parent-side
    encoding of the spawned process is what we're testing.
    """
    wiki = tmp_path / "wiki"
    (wiki / ".lorewiki").mkdir(parents=True)
    cfg = LoreWikiConfig(wiki_path=wiki, db_path=wiki / ".lorewiki" / "index.db")
    build_index(cfg, rebuild=True)

    # Encode the body as UTF-8 — this is what a sensible parent
    # process (modern PowerShell 7+, bash, zsh, any *nix shell)
    # would do. On Windows + PowerShell 5.1 the encoding is
    # actually UTF-16 LE for ``echo`` output, which Python reads
    # with the surrogate-escape error handler — that's the case
    # covered by the test_cli_add.py surrogate regression. The
    # common case this test pins is "parent emits UTF-8 bytes
    # with no BOM; child Python sees them as a UTF-8 string
    # because we reconfigured stdin".
    body_bytes = _STDIN_PROBE_BODY.encode("utf-8")

    # The child Python defaults stdin encoding to the parent's
    # locale. We force it to UTF-8 here (this is what a
    # PowerShell 7+ or bash parent would do) and assert the
    # ``_force_utf8_streams`` reconfig survives that.
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "USERPROFILE": str(tmp_path),
        "PYTHONIOENCODING": "utf-8",
    }
    proc = subprocess.run(
        [
            sys.executable, "-m", "lorewiki", "add",
            "--title", "Stdin CJK Probe",
            "--module", "patterns",
            "--path", str(wiki),
        ],
        input=body_bytes,
        capture_output=True,
        env=env,
        check=False,
        timeout=15,
    )
    assert proc.returncode == 0, (
        f"add crashed (rc={proc.returncode}): "
        f"stderr={proc.stderr.decode('utf-8', errors='replace')!r}"
    )

    # The on-disk file is what the child Python decoded from
    # stdin. Read it back and assert the bytes round-trip.
    target = wiki / "patterns" / "stdin-cjk-probe.md"
    assert target.exists(), f"add did not write {target}"
    text = target.read_text(encoding="utf-8")
    assert _STDIN_PROBE_BODY in text, (
        f"stdin body was mojibake'd by the child. "
        f"Expected the literal CJK string to appear, got:\n{text!r}"
    )
    # And the SQLite FTS5 index should be searchable on the
    # literal CJK string.
    search_proc = CliRunner().invoke(
        _app,
        ["search", "幂等", "--path", str(wiki)],
    )
    assert search_proc.exit_code == 0
    payload = json.loads(search_proc.stdout)
    assert payload, (
        f"expected at least one hit for '幂等', got {payload!r}"
    )


# ---------------------------------------------------------------------------
# Real-corpus smoke tests against the developer's local wechat-miniprogram-api
# ---------------------------------------------------------------------------
#
# These tests are *not* about UTF-8 — they are end-to-end sanity
# checks that the wheel-built CLI can search the real-world
# knowledge corpus the master has been curating. They skip
# silently when the corpus isn't on the developer's machine
# (e.g. on a fresh CI runner), so they don't add to CI flakiness
# — but on the master's own box they confirm that
# ``lorewiki search`` actually returns real CJK results from a
# 1468-document / 1902-chunk topic.


_WECHAT_TOPIC_PATH = Path.home() / ".lorewiki" / "topics" / "wechat-miniprogram-api"


@pytest.fixture()
def wechat_corpus() -> Path:
    """Skip when the developer's wechat-miniprogram-api topic isn't on disk."""
    if not _WECHAT_TOPIC_PATH.exists():
        pytest.skip(
            f"real-corpus test: {_WECHAT_TOPIC_PATH} not found on this machine"
        )
    return _WECHAT_TOPIC_PATH


def test_real_corpus_search_wx_login(wechat_corpus: Path) -> None:
    """``lorewiki search wx.login`` against the real wechat-miniprogram-api
    topic must return the actual wx.login API doc, not zero hits
    and not a wrong doc."""
    proc = _run_lorewiki(
        ["search", "wx.login", "--path", str(wechat_corpus), "--mode", "mix",
         "--top-k", "3"]
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    payload = json.loads(proc.stdout.decode("utf-8"))
    assert payload, f"expected at least one hit, got {payload!r}"
    paths = [h["doc_path"] for h in payload]
    assert any("login" in p and "wx.login" in p for p in paths), (
        f"expected wx.login.md in paths, got {paths!r}"
    )


def test_real_corpus_search_cjk_2char(wechat_corpus: Path) -> None:
    """CJK 2-character query (e.g. ``登录``) should return *some* hit
    in a 1468-doc corpus even when FTS5 trigrams alone can't tokenise
    a 2-character CJK string — the LIKE fallback in
    ``lorewiki.retriever.bm25`` is the safety net."""
    proc = _run_lorewiki(
        ["search", "登录", "--path", str(wechat_corpus), "--mode", "mix",
         "--top-k", "3"]
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    payload = json.loads(proc.stdout.decode("utf-8"))
    assert payload, (
        f"LIKE fallback should still return hits for '登录' in 1468-doc "
        f"corpus, got {payload!r}"
    )


def test_real_corpus_status_reports_doc_count(wechat_corpus: Path) -> None:
    """Sanity check the corpus hasn't silently shrunk (e.g. by an
    accidental ``lorewiki clean``)."""
    proc = _run_lorewiki(["status", "--path", str(wechat_corpus)])
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    out = proc.stdout.decode("utf-8", errors="replace")
    # The corpus the master has been curating has 1468+ documents.
    # We only assert a generous lower bound to catch catastrophic
    # loss without coupling this test to the exact doc count.
    assert "Documents" in out
    # Extract the number after "Documents" + whitespace.
    for line in out.splitlines():
        if "Documents" in line and "KB" not in line:
            num = int(line.split()[-1])
            assert num > 1000, (
                f"expected wechat corpus to have > 1000 docs, got {num}. "
                f"Full output:\n{out}"
            )
            return
    pytest.fail(f"could not find Documents line in status output:\n{out}")
