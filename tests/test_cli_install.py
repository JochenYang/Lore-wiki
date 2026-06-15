"""Unit tests for the wheel-side ``lorewiki install`` subcommand.

These tests:

- Confirm the bundled ``SKILL.md`` is readable from
  ``lorewiki.data.skill_template`` (i.e. the wheel-build wiring
  is correct).
- Exercise ``_parse_choice`` against the same grammar the
  source-tree ``skills/install.py`` accepts, ensuring the two
  paths stay in sync.
- Drive the install / uninstall / status round-trip against a
  synthetic ``$HOME`` and check that paths resolve cross-platform
  style (forward slashes; the temp dirs are platform-agnostic).
- Use ``typer.testing.CliRunner`` to drive the full
  ``lorewiki install`` Typer command end-to-end.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from lorewiki.cli.apps import app
from lorewiki.utils import skill_installer as si

runner = CliRunner()


# ---------------------------------------------------------------------------
# _parse_choice
# ---------------------------------------------------------------------------


class TestParseChoice:
    """Cover the full prompt grammar.

    The same matrix is asserted for the source-tree
    ``skills/install.py`` (see ``tests/test_skill_installer.py``);
    the two test classes must agree on every input.
    """

    @pytest.mark.parametrize("raw", ["", "  ", "q", "Q", "quit", "QUIT"])
    def test_quit_forms(self, raw: str) -> None:
        assert si._parse_choice(raw, max_n=6) == "quit"

    @pytest.mark.parametrize("raw", ["a", "A", "all", "ALL"])
    def test_all_forms(self, raw: str) -> None:
        assert si._parse_choice(raw, max_n=6) == "all"

    def test_single_digit(self) -> None:
        assert si._parse_choice("3", max_n=6) == [3]

    def test_comma_separated(self) -> None:
        assert si._parse_choice("1,3,5", max_n=6) == [1, 3, 5]

    def test_space_separated(self) -> None:
        assert si._parse_choice("1 3 5", max_n=6) == [1, 3, 5]

    def test_mixed_separators(self) -> None:
        assert si._parse_choice(" 1 , 3\t5 ", max_n=6) == [1, 3, 5]

    def test_range_token(self) -> None:
        assert si._parse_choice("2-4", max_n=6) == [2, 3, 4]

    def test_mixed_digits_and_ranges(self) -> None:
        assert si._parse_choice("1,3-5,6", max_n=6) == [1, 3, 4, 5, 6]

    def test_duplicates_are_deduped(self) -> None:
        assert si._parse_choice("1,1,1", max_n=6) == [1]
        assert si._parse_choice("1-3,2", max_n=6) == [1, 2, 3]

    @pytest.mark.parametrize(
        "raw",
        [
            "7", "1,7", "2-7", "0", "1,0,3", "5-3",
            "abc", "1.5", "-1", "1-",
        ],
    )
    def test_invalid_inputs_return_none(self, raw: str) -> None:
        assert si._parse_choice(raw, max_n=6) is None

    def test_respects_max_n(self) -> None:
        assert si._parse_choice("2-4", max_n=3) is None
        assert si._parse_choice("1-2", max_n=3) == [1, 2]


# ---------------------------------------------------------------------------
# Bundled SKILL.md (wheel package-data wiring)
# ---------------------------------------------------------------------------


def test_bundled_skill_md_is_readable() -> None:
    """The wheel must include the SKILL.md as package data; if the
    ``pyproject.toml`` ``include`` list is wrong, this fails with
    ``FileNotFoundError`` (the importlib.resources call inside
    ``_read_skill_template`` raises)."""
    text = si._read_skill_template()
    # Sanity: it's the real skill document, not a placeholder.
    assert "name: lorewiki" in text
    assert len(text) > 5000  # SKILL.md is ~29 KB


# ---------------------------------------------------------------------------
# detect_installed_tools — cross-platform
# ---------------------------------------------------------------------------


def test_detect_finds_explicit_config_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``~/.config/opencode/`` (or its macOS/Linux equivalent) is
    the canonical "the tool is installed" signal. We synthesize
    two such roots and confirm detect picks them up regardless
    of platform."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))

    # Lay down two fake config roots.
    (tmp_path / ".config" / "opencode").mkdir(parents=True)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".cursor").mkdir()  # this one also creates an alias below

    found = {t.id for t in si.detect_installed_tools()}
    assert "opencode" in found
    assert "claude" in found
    assert "cursor" in found
    # No "no tool" tools should be present.
    assert "codex" not in found  # ~/.codex was not created

    # Cross-platform path check: the resolved paths use forward
    # slashes on POSIX, backslashes on Windows; either way the
    # ``Path`` ctor handles them. Confirm the paths are absolute.
    opencode_tool = next(t for t in si.TOOLS if t.id == "opencode")
    p = opencode_tool.resolve(opencode_tool.primary)
    assert p.is_absolute()


def test_detect_empty_when_no_config_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the home is empty, detect should return an empty list,
    not silently include every tool just because their config
    roots would resolve under $HOME if it existed."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    # Create the home dir but no tool config roots under it.
    assert si.detect_installed_tools() == []


# ---------------------------------------------------------------------------
# install_skill / uninstall_skill — round-trip
# ---------------------------------------------------------------------------


def test_install_writes_skill_to_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Install writes SKILL.md to the tool's primary path."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    (tmp_path / ".config" / "opencode").mkdir(parents=True)

    opencode = next(t for t in si.TOOLS if t.id == "opencode")
    actions = si.install_skill(opencode)
    assert any("wrote" in line and "[ok]" in line for line in actions)

    target = opencode.resolve(opencode.primary)
    assert target.exists()
    assert "name: lorewiki" in target.read_text(encoding="utf-8")


def test_install_refuses_to_overwrite_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a SKILL.md is already at the target, install must skip and
    surface a friendly hint — not silently clobber the user's edit."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    (tmp_path / ".config" / "opencode").mkdir(parents=True)

    opencode = next(t for t in si.TOOLS if t.id == "opencode")
    target = opencode.resolve(opencode.primary)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("USER EDIT\n", encoding="utf-8")

    actions = si.install_skill(opencode)
    assert any("[skip]" in line for line in actions)
    assert target.read_text(encoding="utf-8") == "USER EDIT\n"

    # --force overwrites.
    si.install_skill(opencode, overwrite=True)
    assert "name: lorewiki" in target.read_text(encoding="utf-8")


def test_install_creates_aliases_for_cursor_and_gemini(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cursor and Gemini have a second alias under ``~/.agents/``;
    installing into either should also plant a copy there."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".agents").mkdir()  # alias root

    cursor = next(t for t in si.TOOLS if t.id == "cursor")
    si.install_skill(cursor)

    primary = cursor.resolve(cursor.primary)
    alias = cursor.resolve(cursor.aliases[0])
    assert primary.exists()
    assert alias.exists()
    # Both are the same content (byte-identical copy, not symlink).
    assert primary.read_bytes() == alias.read_bytes()


def test_install_skips_locked_primary_keeps_going_to_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for 0.2.8: if the primary path is locked (e.g.
    Cursor writes a ``.skill-lock.json`` while the agent is
    running, which surfaces as ``PermissionError`` on
    ``write_text``), the alias path still gets a copy.

    Before 0.2.8, ``primary.write_text()`` raised out of
    ``install_skill`` and the ``for alias_tmpl in tool.aliases:``
    loop was never entered — so the alias path was silently
    never created and ``--status`` showed ``[ ]`` forever.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".agents").mkdir()

    cursor = next(t for t in si.TOOLS if t.id == "cursor")
    primary_path = cursor.resolve(cursor.primary)
    alias_path = cursor.resolve(cursor.aliases[0])

    # Lock the primary path: write_text on the *file* should fail
    # with PermissionError. The cheapest portable fake is to
    # replace it on the file itself, not on a directory lock —
    # we can simulate the failure by patching write_text on the
    # primary path only.
    real_write_text = type(primary_path).write_text

    def fake_write_text(self, *a, **kw):
        if self == primary_path:
            raise PermissionError(13, "Permission denied", str(self))
        return real_write_text(self, *a, **kw)

    monkeypatch.setattr(type(primary_path), "write_text", fake_write_text)

    actions = si.install_skill(cursor)

    # The alias path *must* be created even though the primary
    # write failed.
    assert alias_path.exists(), (
        f"alias was not written because primary write failed.\n"
        f"actions: {actions!r}"
    )
    # The action list reports both the failure and the success.
    assert any("write failed" in line for line in actions)
    assert any("wrote" in line and "alias" in line for line in actions)


def test_uninstall_continues_past_locked_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mirror of :func:`test_install_skips_locked_primary_keeps_going_to_alias`
    for the uninstall path."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".agents").mkdir()

    cursor = next(t for t in si.TOOLS if t.id == "cursor")
    # Pre-populate both targets.
    si.install_skill(cursor)

    primary_path = cursor.resolve(cursor.primary)
    alias_path = cursor.resolve(cursor.aliases[0])
    assert primary_path.exists() and alias_path.exists()

    real_unlink = type(primary_path).unlink

    def fake_unlink(self, *a, **kw):
        if self == primary_path:
            raise PermissionError(13, "Permission denied", str(self))
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(type(primary_path), "unlink", fake_unlink)

    actions = si.uninstall_skill(cursor)

    assert not alias_path.exists(), (
        f"alias should have been removed even though primary was "
        f"locked. actions={actions!r}"
    )
    assert any("unlink failed" in line for line in actions)
    # The alias path was successfully unlinked (the [rm] action
    # line points at the alias path).
    rm_lines = [line for line in actions if line.startswith("[rm]")]
    assert any(str(alias_path) in line for line in rm_lines), (
        f"expected an [rm] action for {alias_path}, got {rm_lines!r}"
    )


def test_uninstall_removes_primary_and_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    (tmp_path / ".config" / "opencode").mkdir(parents=True)

    opencode = next(t for t in si.TOOLS if t.id == "opencode")
    si.install_skill(opencode)
    target = opencode.resolve(opencode.primary)
    assert target.exists()

    si.uninstall_skill(opencode)
    assert not target.exists()


# ---------------------------------------------------------------------------
# status_report
# ---------------------------------------------------------------------------


def test_status_marks_installed_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The status block must mark Cursor with ``[x]`` for both the
    primary and the alias, since they are independent paths."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".agents").mkdir()

    cursor = next(t for t in si.TOOLS if t.id == "cursor")
    si.install_skill(cursor)

    text = si.status_report()
    # Cursor primary line should be ``[x]``; alias line should be
    # ``[x]`` too because Cursor's primary is the canonical
    # alias to ``~/.agents/skills/``.
    cursor_lines = [
        ln for ln in text.splitlines() if "Cursor" in ln and "alias" not in ln
    ]
    alias_lines = [ln for ln in text.splitlines() if "alias" in ln]
    assert cursor_lines and cursor_lines[0].startswith("  [x] Cursor")
    assert any(ln.startswith("  [x]   alias") for ln in alias_lines)


# ---------------------------------------------------------------------------
# prompt_for_targets — interactive
# ---------------------------------------------------------------------------


def test_prompt_quit_returns_none(capsys: pytest.CaptureFixture[str]) -> None:
    detected = [si.TOOLS[0]]
    assert si.prompt_for_targets(detected, input_fn=lambda _: "q") is None
    out = capsys.readouterr().out
    assert "Detected tools" in out


def test_prompt_all_returns_full_list(capsys: pytest.CaptureFixture[str]) -> None:
    detected = list(si.TOOLS[:3])
    assert si.prompt_for_targets(detected, input_fn=lambda _: "a") == detected


def test_prompt_single_returns_one(
    capsys: pytest.CaptureFixture[str],
) -> None:
    detected = list(si.TOOLS[:3])
    out = si.prompt_for_targets(detected, input_fn=lambda _: "2")
    assert out == [si.TOOLS[1]]


def test_prompt_multi_returns_subset(
    capsys: pytest.CaptureFixture[str],
) -> None:
    detected = list(si.TOOLS[:3])
    out = si.prompt_for_targets(detected, input_fn=lambda _: "1,3")
    assert out == [si.TOOLS[0], si.TOOLS[2]]


def test_prompt_invalid_returns_none(
    capsys: pytest.CaptureFixture[str],
) -> None:
    detected = list(si.TOOLS[:3])
    assert si.prompt_for_targets(detected, input_fn=lambda _: "bogus") is None
    err = capsys.readouterr().err
    assert "invalid choice" in err


# ---------------------------------------------------------------------------
# Typer subcommand end-to-end
# ---------------------------------------------------------------------------


def test_install_subcommand_lists_in_help(capsys: pytest.CaptureFixture[str]) -> None:
    """``lorewiki install`` must be visible in ``lorewiki --help``."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "install" in result.stdout


def test_install_status_subcommand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    (tmp_path / ".config" / "opencode").mkdir(parents=True)

    result = runner.invoke(app, ["install", "--status"])
    assert result.exit_code == 0, result.output
    assert "LoreWiki skill status" in result.stdout
    assert "opencode" in result.stdout


def test_install_all_writes_to_every_detected_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    (tmp_path / ".config" / "opencode").mkdir(parents=True)
    (tmp_path / ".claude").mkdir()

    result = runner.invoke(app, ["install", "--all"])
    assert result.exit_code == 0, result.output

    # Both tools should now have SKILL.md at their primary path.
    opencode = next(t for t in si.TOOLS if t.id == "opencode")
    claude = next(t for t in si.TOOLS if t.id == "claude")
    assert opencode.resolve(opencode.primary).exists()
    assert claude.resolve(claude.primary).exists()


def test_install_explicit_tool_with_unknown_id_errors() -> None:
    result = runner.invoke(app, ["install", "--tool", "not-a-real-tool"])
    assert result.exit_code == 2
    # ``runner.invoke`` captures both streams into ``result.*``;
    # we wrote the diagnostic to ``sys.stderr`` in ``skill_installer.run``.
    assert "unknown --tool ids" in (result.stderr or "")
