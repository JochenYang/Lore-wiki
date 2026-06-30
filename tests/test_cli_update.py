"""Integration tests for the ``lorewiki update`` command.

Covers:

1. Body-only update → new content lands on disk + is searchable.
2. Frontmatter-only update (title / module / tags) with the body
   preserved.
3. ``--raw`` JSON output.
4. Document-not-found error handling.
5. Path-traversal protection.
6. Reindex reflects the change: the new body is retrievable, the old
   body no longer ranks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lorewiki.cli.apps import app

runner = CliRunner()


@pytest.fixture()
def fresh_wiki(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A blank wiki root: ``.lorewiki/config.toml`` only, no .md files."""
    wiki = tmp_path / "wiki"
    (wiki / ".lorewiki").mkdir(parents=True)
    (wiki / ".lorewiki" / "config.toml").write_text(
        'retrieval_mode = "bm25"\n', encoding="utf-8"
    )
    # Re-route ``~/lorewiki/current`` and friends to a writable scratch
    # dir so the CLI's resolve_config doesn't try to create the user's
    # real home tree on test runs.
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("LOREWIKI_WIKI_PATH", str(wiki))
    return wiki


def _add_doc(wiki: Path, *, title: str, body: str, module: str = "root") -> None:
    """Helper: create a doc via the ``add`` command."""
    result = runner.invoke(
        app,
        [
            "add",
            "--title",
            title,
            "--body",
            body,
            "--module",
            module,
            "--path",
            str(wiki),
        ],
    )
    assert result.exit_code == 0, result.output


def _search(wiki: Path, query: str) -> list[dict[str, object]]:
    """Helper: run ``lorewiki search`` and return the JSON payload."""
    result = runner.invoke(
        app,
        ["search", query, "--path", str(wiki), "--top-k", "5"],
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# 1. body-only update
# ---------------------------------------------------------------------------


def test_cli_update_replaces_body_and_is_searchable(fresh_wiki: Path) -> None:
    _add_doc(
        fresh_wiki,
        title="Update Me",
        body="original alpha unique token here",
    )
    target = fresh_wiki / "root" / "update-me.md"
    assert target.exists()

    result = runner.invoke(
        app,
        [
            "update",
            str(target.relative_to(fresh_wiki)),
            "--body",
            "refreshed beta unique token here",
            "--path",
            str(fresh_wiki),
        ],
    )
    assert result.exit_code == 0, result.output

    text = target.read_text(encoding="utf-8")
    assert "refreshed beta unique token here" in text
    assert "original alpha" not in text

    hits = _search(fresh_wiki, "beta")
    assert any("update-me" in str(h["doc_path"]) for h in hits)


# ---------------------------------------------------------------------------
# 2. frontmatter-only update (body preserved)
# ---------------------------------------------------------------------------


def test_cli_update_frontmatter_preserves_body(fresh_wiki: Path) -> None:
    _add_doc(
        fresh_wiki,
        title="Keep Body",
        body="this body must survive the update",
    )
    target = fresh_wiki / "root" / "keep-body.md"

    result = runner.invoke(
        app,
        [
            "update",
            str(target.relative_to(fresh_wiki)),
            "--title",
            "Renamed Title",
            "--tag",
            "fresh",
            "--path",
            str(fresh_wiki),
        ],
    )
    assert result.exit_code == 0, result.output

    text = target.read_text(encoding="utf-8")
    # Body untouched.
    assert "this body must survive the update" in text
    # New title + tag in frontmatter.
    assert "Renamed Title" in text
    assert "fresh" in text
    # The file did not move (overwrite in place).
    assert target.exists()


# ---------------------------------------------------------------------------
# 3. --raw output
# ---------------------------------------------------------------------------


def test_cli_update_raw_output_is_json(fresh_wiki: Path) -> None:
    _add_doc(fresh_wiki, title="Raw Update", body="initial")
    target = fresh_wiki / "root" / "raw-update.md"

    result = runner.invoke(
        app,
        [
            "update",
            str(target.relative_to(fresh_wiki)),
            "--title",
            "Raw Updated",
            "--raw",
            "--path",
            str(fresh_wiki),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True
    assert payload["title"] == "Raw Updated"
    assert payload["path"].endswith("raw-update.md")


# ---------------------------------------------------------------------------
# 4. document not found
# ---------------------------------------------------------------------------


def test_cli_update_errors_when_doc_missing(fresh_wiki: Path) -> None:
    result = runner.invoke(
        app,
        [
            "update",
            "nope/does-not-exist.md",
            "--body",
            "anything",
            "--path",
            str(fresh_wiki),
        ],
    )
    assert result.exit_code != 0
    assert "Document not found" in result.output


# ---------------------------------------------------------------------------
# 5. path-traversal protection
# ---------------------------------------------------------------------------


def test_cli_update_blocks_path_traversal(fresh_wiki: Path) -> None:
    """A doc_path that resolves outside the wiki root must be rejected."""
    # Plant a file outside the wiki to tempt the command.
    evil = fresh_wiki.parent / "evil-secret.md"
    evil.write_text("secret", encoding="utf-8")
    try:
        result = runner.invoke(
            app,
            [
                "update",
                str(evil),
                "--body",
                "hacked",
                "--path",
                str(fresh_wiki),
            ],
        )
        assert result.exit_code != 0
        assert "path-traversal" in result.output.lower()
        # The outside file is untouched.
        assert evil.read_text(encoding="utf-8") == "secret"
    finally:
        evil.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 6. reindex reflects the change (old content gone, new content in)
# ---------------------------------------------------------------------------


def test_cli_update_reindex_drops_old_content(fresh_wiki: Path) -> None:
    """After updating the body, searching the OLD unique token must not
    return the doc — proves the incremental reindex rewrote the chunks
    rather than leaving stale rows behind."""
    _add_doc(
        fresh_wiki,
        title="Stale Check",
        body="zzz-old-unique-token zzz-old-unique-token",
    )
    target = fresh_wiki / "root" / "stale-check.md"

    # Sanity: the old token is retrievable before the update.
    hits_before = _search(fresh_wiki, "zzz-old-unique-token")
    assert any("stale-check" in str(h["doc_path"]) for h in hits_before)

    result = runner.invoke(
        app,
        [
            "update",
            str(target.relative_to(fresh_wiki)),
            "--body",
            "zzz-new-unique-token zzz-new-unique-token",
            "--path",
            str(fresh_wiki),
        ],
    )
    assert result.exit_code == 0, result.output

    # New token is now retrievable.
    hits_new = _search(fresh_wiki, "zzz-new-unique-token")
    assert any("stale-check" in str(h["doc_path"]) for h in hits_new)

    # Old token is no longer in the index for this doc.
    hits_old = _search(fresh_wiki, "zzz-old-unique-token")
    assert not any("stale-check" in str(h["doc_path"]) for h in hits_old)
