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
from lorewiki.topic import TopicManager

runner = CliRunner()


def _patch_lorewiki_home(monkeypatch: pytest.MonkeyPatch, fake_home: Path) -> None:
    monkeypatch.setattr("lorewiki.config.USER_CONFIG_DIR", fake_home)
    monkeypatch.setattr("lorewiki.config.USER_CONFIG_PATH", fake_home / "config.toml")
    monkeypatch.setattr("lorewiki.topic.USER_CONFIG_DIR", fake_home)
    monkeypatch.setattr("lorewiki.topic.USER_TOPICS_ROOT", fake_home / "topics")
    monkeypatch.setattr("lorewiki.topic.CURRENT_FILE", fake_home / "current")
    monkeypatch.setattr("lorewiki.utils.topic_shared.USER_CONFIG_DIR", fake_home)
    monkeypatch.setattr("lorewiki.utils.topic_shared.USER_TOPICS_ROOT", fake_home / "topics")
    monkeypatch.setattr("lorewiki.utils.topic_shared.CURRENT_FILE", fake_home / "current")



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


def test_cli_add_strips_surrogates_from_stdin(fresh_wiki: Path) -> None:
    """Regression for 0.2.1: Windows PowerShell pipes strings as UTF-16
    LE, and Python's stdin reader can surface those bytes as **lone**
    surrogate codepoints (U+D800..U+DFFF). UTF-8 cannot encode lone
    surrogates, so before this fix the subprocess crashed with
    ``UnicodeEncodeError: surrogates not allowed`` and left a 0-byte
    file on disk. The fix: ``_read_body`` scrubs the stdin stream via
    ``_strip_surrogates`` before passing the body to ``frontmatter``.

    We test two layers:

    1. **Unit**: ``_strip_surrogates`` does the right thing on the
       pathological codepoint range (lone high, lone low, mixed with
       real CJK).
    2. **End-to-end**: ``add`` with a ``--body`` that contains lone
       surrogates writes the file successfully (no UnicodeEncodeError,
       no 0-byte garbage on disk) and the surrogates are replaced with
       U+FFFD in the output.

    The actual PowerShell-pipe round-trip is Windows-specific; the
    CliRunner path exercises the same ``_strip_surrogates`` →
    ``frontmatter.dumps`` → ``write_text('utf-8')`` code path without
    needing a real PowerShell.
    """
    from lorewiki.cli.add import _strip_surrogates  # noqa: PLC0415

    # ---- 1. unit: _strip_surrogates --------------------------------------
    # Lone high + lone low individually.
    assert _strip_surrogates("\ud83d") == "\ufffd"
    assert _strip_surrogates("\ude00") == "\ufffd"
    # Mixed: real CJK + surrogate pair (the realistic case).
    assert _strip_surrogates("幂等 \ud83d\ude00 一切") == "幂等 \ufffd\ufffd 一切"
    # Idempotence: running twice == running once.
    once = _strip_surrogates("幂等 \ud83d\ude00 一切")
    twice = _strip_surrogates(once)
    assert once == twice
    # No-surrogate input is a no-op.
    assert _strip_surrogates("幂等 一切") == "幂等 一切"

    # ---- 2. end-to-end: add --body with lone surrogates ------------------
    body = "# Surrogate Note\n\n幂等设计 \ud83d\ude00 一切正常。\n"
    # sanity: confirm our test fixture actually contains a lone
    # surrogate pair, otherwise the test is meaningless.
    assert any(0xD800 <= ord(ch) <= 0xDFFF for ch in body)

    result = runner.invoke(
        app,
        [
            "add",
            "--title",
            "Surrogate Note",
            "--module",
            "notes",
            "--body",
            body,
            "--path",
            str(fresh_wiki),
        ],
    )
    assert result.exit_code == 0, (
        f"add with surrogate body crashed (rc={result.exit_code}): "
        f"stdout={result.stdout!r}"
    )
    target = fresh_wiki / "notes" / "surrogate-note.md"
    assert target.exists()
    size = target.stat().st_size
    assert size > 0, "0-byte file left behind — write cleanup regression"
    text = target.read_text(encoding="utf-8")
    # The real (CJK) characters must survive untouched.
    assert "幂等设计" in text
    assert "一切正常" in text
    # The lone surrogate must be replaced with U+FFFD, not silently
    # dropped (so the user knows the original character didn't make it).
    assert "\ufffd" in text
    # And of course the original surrogate codepoints must NOT be in
    # the file (they are illegal UTF-8 and ``read_text('utf-8')``
    # would crash on them anyway).
    assert "\ud83d" not in text
    assert "\ude00" not in text


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


def test_cli_add_with_topic_reindexes_selected_topic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    _patch_lorewiki_home(monkeypatch, fake_home)
    mgr = TopicManager()
    mgr.create("active-topic")
    target_info = mgr.create("target-topic")
    mgr.use("active-topic")

    result = runner.invoke(
        app,
        [
            "add",
            "--title",
            "Target Topic Note",
            "--body",
            "Only the target topic should index this unique phrase.",
            "--topic",
            "target-topic",
        ],
    )

    assert result.exit_code == 0, result.output
    assert (target_info.wiki_path / "root" / "target-topic-note.md").exists()

    try:
        search_result = runner.invoke(
            app,
            [
                "--topic",
                "target-topic",
                "search",
                "unique phrase",
                "--top-k",
                "3",
            ],
        )
        assert search_result.exit_code == 0, search_result.output
        payload = json.loads(search_result.stdout)
        assert any("target-topic-note" in h["doc_path"] for h in payload)
    finally:
        monkeypatch.delenv("LOREWIKI_TOPIC", raising=False)
