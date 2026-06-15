"""Integration tests for the ``lorewiki add`` command.

Covers the five scenarios the implementation plan calls out:

1. ``--body`` write → file is created, immediately retrievable via search.
2. Stdin pipe write → file is created with piped content.
3. Conflict detection: refusing overwrite without ``--force``; honouring
   ``--force`` when the caller asks for it.
4. Path-traversal protection: a dangerous ``--module`` value (or
   anything that resolves outside the wiki root) is rejected.
5. ``--raw`` JSON output format.
"""

from __future__ import annotations

import json
import subprocess
import sys
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


# ---------------------------------------------------------------------------
# 1. --body write
# ---------------------------------------------------------------------------


def test_cli_add_writes_body_and_makes_doc_searchable(fresh_wiki: Path) -> None:
    result = runner.invoke(
        app,
        [
            "add",
            "--title",
            "Python Design",
            "--module",
            "patterns",
            "--body",
            "Some deep details about Python design pattern.",
            "--tag",
            "python",
            "--tag",
            "design",
            "--path",
            str(fresh_wiki),
        ],
    )
    assert result.exit_code == 0, result.output

    # The file landed at the expected slugified path.
    target = fresh_wiki / "patterns" / "python-design.md"
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert "Some deep details about Python design pattern." in text
    assert "title:" in text  # YAML frontmatter present
    assert "patterns" in text

    # And it's immediately searchable.
    search_result = runner.invoke(
        app,
        ["search", "design pattern", "--path", str(fresh_wiki), "--top-k", "3"],
    )
    assert search_result.exit_code == 0, search_result.output
    payload = json.loads(search_result.stdout)
    assert any("python-design" in h["doc_path"] for h in payload)


# ---------------------------------------------------------------------------
# 2. stdin pipe write
# ---------------------------------------------------------------------------


def test_cli_add_reads_body_from_stdin(fresh_wiki: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "lorewiki",
            "add",
            "--title",
            "Stdin Note",
            "--module",
            "notes",
            "--path",
            str(fresh_wiki),
        ],
        input="# Piped\n\nThis note arrived via stdin.\n",
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        env={
            **__import__("os").environ,
            "HOME": str(fresh_wiki.parent / "home"),
            "USERPROFILE": str(fresh_wiki.parent / "home"),
        },
    )
    assert proc.returncode == 0, proc.stderr
    target = fresh_wiki / "notes" / "stdin-note.md"
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert "This note arrived via stdin." in text
    assert "title:" in text


# ---------------------------------------------------------------------------
# 3. Conflict detection
# ---------------------------------------------------------------------------


def test_cli_add_refuses_overwrite_without_force(fresh_wiki: Path) -> None:
    target = fresh_wiki / "root"
    target.mkdir(parents=True, exist_ok=True)
    (target / "clash.md").write_text(
        "---\ntitle: 'old'\nmodule: root\n---\n\nold body\n", encoding="utf-8"
    )

    result = runner.invoke(
        app,
        [
            "add",
            "--title",
            "clash",
            "--body",
            "new body",
            "--path",
            str(fresh_wiki),
        ],
    )
    # Refusal: exit code != 0, the on-disk file is unchanged.
    assert result.exit_code != 0
    assert "File already exists" in result.output
    assert (target / "clash.md").read_text(encoding="utf-8").endswith("old body\n")


def test_cli_add_force_overwrites_existing(fresh_wiki: Path) -> None:
    target = fresh_wiki / "root"
    target.mkdir(parents=True, exist_ok=True)
    (target / "clash.md").write_text(
        "---\ntitle: 'old'\nmodule: root\n---\n\nold body\n", encoding="utf-8"
    )

    result = runner.invoke(
        app,
        [
            "add",
            "--title",
            "clash",
            "--body",
            "new body",
            "--force",
            "--path",
            str(fresh_wiki),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "new body" in (target / "clash.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 4. Path-traversal protection
# ---------------------------------------------------------------------------


def test_cli_add_blocks_path_traversal_in_module(fresh_wiki: Path) -> None:
    """The slugifier collapses ``../`` segments into a safe name so the
    first line of defence is silent. The real safety net is the
    ``_is_safe_target`` check: a file whose path resolves outside the
    wiki root must be rejected. We exercise it directly so the test
    doesn't depend on the slugifier being a complete filter."""
    from lorewiki.cli.add import _is_safe_target  # noqa: PLC0415

    # These all resolve outside the wiki root — must be rejected.
    assert not _is_safe_target(fresh_wiki, fresh_wiki.parent / "evil.md")
    assert not _is_safe_target(fresh_wiki, fresh_wiki.parent.parent / "evil.md")
    # ``fresh_wiki`` itself is the wiki root — must be rejected too
    # (writing *at* the root would clobber the directory itself).
    assert not _is_safe_target(fresh_wiki, fresh_wiki)
    # A safe target inside the wiki tree is accepted.
    assert _is_safe_target(fresh_wiki, fresh_wiki / "api" / "auth.md")
    assert _is_safe_target(fresh_wiki, fresh_wiki / "patterns" / "python.md")


def test_cli_add_module_with_dotdot_slugifies_safely(fresh_wiki: Path) -> None:
    """The CLI's slugifier should normalise a ``../``-laden module name
    into a single safe segment, so no actual path-traversal can occur
    even if the safety net is somehow bypassed."""
    result = runner.invoke(
        app,
        [
            "add",
            "--title",
            "evil",
            "--body",
            "should not land",
            "--module",
            "../../../../etc",
            "--path",
            str(fresh_wiki),
        ],
    )
    # Either the safety net fired (exit code != 0), or the slugifier
    # collapsed the input into a safe directory inside the wiki root.
    # Either way: the only file written is inside ``fresh_wiki``.
    if result.exit_code == 0:
        # The slugifier collapses ``../../../../etc`` to ``etc``; the
        # file should be at ``<wiki>/etc/evil.md``.
        target = fresh_wiki / "etc" / "evil.md"
        assert target.exists(), (
            f"expected slugified target at {target}, but the file did not land there"
        )
    # The full file tree under fresh_wiki should contain zero files
    # outside its root.
    for path in fresh_wiki.parent.rglob("evil.md"):
        assert str(path).startswith(str(fresh_wiki)), (
            f"file escaped wiki root: {path}"
        )


# ---------------------------------------------------------------------------
# 5. --raw output
# ---------------------------------------------------------------------------


def test_cli_add_raw_output_is_json(fresh_wiki: Path) -> None:
    result = runner.invoke(
        app,
        [
            "add",
            "--title",
            "Raw Output Test",
            "--body",
            "json test",
            "--tag",
            "test",
            "--raw",
            "--path",
            str(fresh_wiki),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True
    assert payload["title"] == "Raw Output Test"
    assert payload["module"] in {"root", "raw-output-test"}  # slug-equal variants
    assert payload["tags"] == ["test"]
    assert payload["path"].endswith("raw-output-test.md")


# ---------------------------------------------------------------------------
# bonus: title inference from H1
# ---------------------------------------------------------------------------


def test_cli_add_infers_title_from_first_h1(fresh_wiki: Path) -> None:
    result = runner.invoke(
        app,
        [
            "add",
            # No --title; the body has a clear H1.
            "--body",
            "# Inferred Title\n\nbody text\n",
            "--path",
            str(fresh_wiki),
        ],
    )
    assert result.exit_code == 0, result.output
    target = fresh_wiki / "root" / "inferred-title.md"
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    # The python-frontmatter library serialises plain string values
    # without quotes (YAML allows it). The title text is the only
    # thing we care about — match flexibly.
    assert (
        "title: Inferred Title" in text
        or 'title: "Inferred Title"' in text
        or "title: 'Inferred Title'" in text
    )
