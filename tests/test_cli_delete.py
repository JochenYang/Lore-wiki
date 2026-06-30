"""Integration tests for the ``lorewiki delete`` command.

Covers:

1. ``--force`` happy path → file removed, search no longer returns it
   (proves the stale-row purge worked, not just the file unlink).
2. Confirmation prompt honoured: ``--force`` skips it; ``n`` aborts.
3. ``--raw`` JSON output.
4. Document-not-found error handling.
5. Path-traversal protection.
6. Reindex reflects the deletion: a unique token that WAS retrievable
   is gone after delete.
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
# 1. --force happy path + reindex reflects deletion
# ---------------------------------------------------------------------------


def test_cli_delete_force_removes_file_and_purges_index(fresh_wiki: Path) -> None:
    _add_doc(
        fresh_wiki,
        title="Delete Me",
        body="ddd-unique-token ddd-unique-token",
    )
    target = fresh_wiki / "root" / "delete-me.md"
    assert target.exists()

    # Sanity: the doc is retrievable before delete.
    hits_before = _search(fresh_wiki, "ddd-unique-token")
    assert any("delete-me" in str(h["doc_path"]) for h in hits_before)

    result = runner.invoke(
        app,
        [
            "delete",
            str(target.relative_to(fresh_wiki)),
            "--force",
            "--path",
            str(fresh_wiki),
        ],
    )
    assert result.exit_code == 0, result.output
    assert not target.exists()

    # The stale chunks must have been purged — search no longer returns
    # the deleted doc. (Without the purge, build_index(rebuild=False)
    # would leave the rows in place and search would still hit them.)
    hits_after = _search(fresh_wiki, "ddd-unique-token")
    assert not any("delete-me" in str(h["doc_path"]) for h in hits_after)


# ---------------------------------------------------------------------------
# 2. confirmation prompt
# ---------------------------------------------------------------------------


def test_cli_delete_prompt_aborts_on_no(fresh_wiki: Path) -> None:
    _add_doc(fresh_wiki, title="Maybe Delete", body="some body")
    target = fresh_wiki / "root" / "maybe-delete.md"

    result = runner.invoke(
        app,
        [
            "delete",
            str(target.relative_to(fresh_wiki)),
            "--path",
            str(fresh_wiki),
        ],
        # Decline the prompt.
        input="n\n",
    )
    assert result.exit_code == 0  # user-initiated abort, not an error
    assert "aborted" in result.output.lower()
    # The file is still there.
    assert target.exists()


def test_cli_delete_prompt_proceeds_on_yes(fresh_wiki: Path) -> None:
    _add_doc(fresh_wiki, title="Confirm Yes", body="some body")
    target = fresh_wiki / "root" / "confirm-yes.md"

    result = runner.invoke(
        app,
        [
            "delete",
            str(target.relative_to(fresh_wiki)),
            "--path",
            str(fresh_wiki),
        ],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    assert not target.exists()


# ---------------------------------------------------------------------------
# 3. --raw output
# ---------------------------------------------------------------------------


def test_cli_delete_raw_output_is_json(fresh_wiki: Path) -> None:
    _add_doc(fresh_wiki, title="Raw Delete", body="bye")
    target = fresh_wiki / "root" / "raw-delete.md"

    result = runner.invoke(
        app,
        [
            "delete",
            str(target.relative_to(fresh_wiki)),
            "--force",
            "--raw",
            "--path",
            str(fresh_wiki),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True
    assert payload["doc_path"] == "root/raw-delete.md"
    assert payload["path"].endswith("raw-delete.md")


# ---------------------------------------------------------------------------
# 4. document not found
# ---------------------------------------------------------------------------


def test_cli_delete_errors_when_doc_missing(fresh_wiki: Path) -> None:
    result = runner.invoke(
        app,
        [
            "delete",
            "nope/does-not-exist.md",
            "--force",
            "--path",
            str(fresh_wiki),
        ],
    )
    assert result.exit_code != 0
    assert "Document not found" in result.output


# ---------------------------------------------------------------------------
# 5. path-traversal protection
# ---------------------------------------------------------------------------


def test_cli_delete_blocks_path_traversal(fresh_wiki: Path) -> None:
    """A doc_path that resolves outside the wiki root must be rejected."""
    evil = fresh_wiki.parent / "evil-outside.md"
    evil.write_text("do not delete me", encoding="utf-8")
    try:
        result = runner.invoke(
            app,
            [
                "delete",
                str(evil),
                "--force",
                "--path",
                str(fresh_wiki),
            ],
        )
        assert result.exit_code != 0
        assert "path-traversal" in result.output.lower()
        # The outside file is untouched.
        assert evil.read_text(encoding="utf-8") == "do not delete me"
    finally:
        evil.unlink(missing_ok=True)
