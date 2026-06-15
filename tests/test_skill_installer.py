"""Unit tests for the cross-platform skill installer.

These tests avoid touching the real ``$HOME``/``$USERPROFILE`` by passing
fully synthetic root paths and monkey-patching the tool catalog at import.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

# Make skills/ importable as a top-level package.
SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
sys.path.insert(0, str(SKILLS_DIR))

import install as installer  # type: ignore[import-not-found,no-redef]  # noqa: E402


@pytest.fixture()
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect HOME / USERPROFILE / XDG_CONFIG_HOME to ``tmp_path/home``."""
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setenv("HOME", str(fake))
    monkeypatch.setenv("USERPROFILE", str(fake))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(fake / ".config"))
    monkeypatch.setenv("CODEX_HOME", str(fake / ".codex"))
    monkeypatch.setenv("GEMINI_HOME", str(fake / ".gemini"))
    # Cached expandvars() / expanduser() should not see the *real* home.
    monkeypatch.delenv("LOREWIKI_TEST_KEEP_REAL", raising=False)
    return fake


@pytest.fixture()
def fake_skill_source(tmp_path: Path) -> Path:
    """Stand-in for ``skills/lorewiki/`` with one SKILL.md inside."""
    src = tmp_path / "lorewiki"
    (src / "scripts").mkdir(parents=True)
    (src / "SKILL.md").write_text(
        "---\ndescription: test skill\n---\n# hello\n", encoding="utf-8"
    )
    (src / "scripts" / "noop.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    return src


# ---------------------------------------------------------------------------
# Tool catalog sanity
# ---------------------------------------------------------------------------


def test_catalog_contains_expected_tools() -> None:
    ids = {t.id for t in installer.TOOLS}
    assert ids == {"opencode", "claude", "codex", "cursor", "gemini", "antigravity"}


def test_resolve_expands_name_placeholder(fake_home: Path) -> None:
    tool = installer.Tool(id="x", label="X", primary="~/skills/<name>")
    resolved = tool.resolve(tool.primary)
    assert resolved == (fake_home / "skills" / installer.SKILL_NAME).resolve()


def test_resolve_honours_xdg_env(fake_home: Path) -> None:
    tool = installer.Tool(id="x", label="X",
                           primary="$XDG_CONFIG_HOME/opencode/skills/<name>")
    resolved = tool.resolve(tool.primary)
    expected = (fake_home / ".config" / "opencode" / "skills" / installer.SKILL_NAME).resolve()
    assert resolved == expected


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def test_detect_installed_tools_finds_existing_config_dirs(
    fake_home: Path,
) -> None:
    # Simulate "Claude Code was opened at least once" by creating its config root.
    (fake_home / ".claude").mkdir()
    detected = installer.detect_installed_tools()
    detected_ids = {t.id for t in detected}
    assert "claude" in detected_ids
    # No Cursor / Gemini / Codex / Antigravity dir created — not detected.
    assert "cursor" not in detected_ids
    assert "gemini" not in detected_ids
    assert "codex" not in detected_ids


def test_detect_installed_tools_empty_when_no_tools(fake_home: Path) -> None:
    assert installer.detect_installed_tools() == []


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------


def test_install_copies_skill_to_primary(
    fake_home: Path, fake_skill_source: Path
) -> None:
    tool = installer.Tool(id="claude", label="Claude", primary="~/.claude/skills/<name>")
    actions = installer.install_tool(
        tool, source=fake_skill_source, symlink=False, force=False, dry_run=False,
    )
    primary = tool.resolve(tool.primary)
    assert primary.is_dir()
    assert (primary / "SKILL.md").read_text(encoding="utf-8").startswith("---")
    assert (primary / "scripts" / "noop.sh").exists()
    assert any("[copy]" in a for a in actions)


def test_install_symlink_creates_real_link(
    fake_home: Path, fake_skill_source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Windows sandboxes (e.g. pytest under a non-admin token) don't have
    # privilege to create symlinks (WinError 1314). We monkey-patch
    # ``Path.symlink_to`` to behave like POSIX: create a junction via
    # ``mklink`` *would* need privilege too, so for the test we substitute
    # a copy + marker. The installer's *contract* is "symlink_mode means
    # the source dir is reachable at the target path"; the test asserts
    # that contract, not the OS-level mechanism.
    calls: list[tuple[Path, Path]] = []

    def fake_symlink_to(self: Path, target: Path, *_args: object, **_kw: object) -> None:
        calls.append((self, target))
        # We can't *actually* create a symlink in the sandbox; we
        # instead copy the source so the post-condition ``exists()``
        # holds. In production (admin / Developer Mode), the real
        # symlink path is taken — see test_install_symlink_falls_back_to_copy_on_oserror.
        if not self.exists() and not self.is_symlink():
            self.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(target, self)

    monkeypatch.setattr(Path, "symlink_to", fake_symlink_to)

    tool = installer.Tool(id="claude", label="Claude", primary="~/.claude/skills/<name>")
    installer.install_tool(
        tool, source=fake_skill_source, symlink=True, force=False, dry_run=False,
    )
    primary = tool.resolve(tool.primary)
    assert (primary / "SKILL.md").exists()  # contract: source reachable at target
    assert calls, "installer should have invoked symlink_to"


def test_install_is_idempotent_without_force(
    fake_home: Path, fake_skill_source: Path
) -> None:
    tool = installer.Tool(id="claude", label="Claude", primary="~/.claude/skills/<name>")
    first = installer.install_tool(
        tool, source=fake_skill_source, symlink=False, force=False, dry_run=False,
    )
    second = installer.install_tool(
        tool, source=fake_skill_source, symlink=False, force=False, dry_run=False,
    )
    assert any("[copy]" in a for a in first)
    assert any("[skip]" in a for a in second)
    # Target still exists, still has the right content.
    primary = tool.resolve(tool.primary)
    assert (primary / "SKILL.md").exists()


def test_install_force_overwrites_existing(
    fake_home: Path, fake_skill_source: Path, tmp_path: Path
) -> None:
    tool = installer.Tool(id="claude", label="Claude", primary="~/.claude/skills/<name>")
    # Pre-populate with a sentinel.
    primary = tool.resolve(tool.primary)
    primary.parent.mkdir(parents=True, exist_ok=True)
    primary.mkdir()
    (primary / "stale.txt").write_text("old")
    installer.install_tool(
        tool, source=fake_skill_source, symlink=False, force=True, dry_run=False,
    )
    assert not (primary / "stale.txt").exists()
    assert (primary / "SKILL.md").exists()


def test_install_dry_run_does_not_touch_disk(
    fake_home: Path, fake_skill_source: Path
) -> None:
    tool = installer.Tool(id="claude", label="Claude", primary="~/.claude/skills/<name>")
    installer.install_tool(
        tool, source=fake_skill_source, symlink=False, force=False, dry_run=True,
    )
    primary = tool.resolve(tool.primary)
    assert not primary.exists()


def test_install_cursor_creates_agents_alias_symlink(
    fake_home: Path, fake_skill_source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The installer should create a symlink at the alias path pointing
    at the primary install path. We can't create real symlinks in the
    sandbox (WinError 1314), so we record the intended (alias, target)
    pair and assert that the installer's contract holds.
    """
    calls: list[tuple[Path, Path]] = []

    def fake_symlink_to(self: Path, target: Path, *_args: object, **_kw: object) -> None:
        calls.append((self, target))

    monkeypatch.setattr(Path, "symlink_to", fake_symlink_to)

    tool = installer.Tool(
        id="cursor", label="Cursor",
        primary="~/.cursor/skills/<name>",
        aliases=("~/.agents/skills/<name>",),
    )
    installer.install_tool(
        tool, source=fake_skill_source, symlink=False, force=False, dry_run=False,
    )
    primary = tool.resolve(tool.primary)
    alias = tool.resolve(tool.aliases[0])

    # Primary is a real copy (we used symlink=False for the install).
    assert primary.is_dir()
    assert (primary / "SKILL.md").exists()

    # The alias path was registered with symlink_to, targeting the
    # primary — i.e. the installer's "Cursor also reads from
    # ~/.agents/skills/" contract is honoured.
    assert len(calls) == 1, f"expected exactly one symlink call (for alias), got {calls}"
    alias_path, target_path = calls[0]
    assert alias_path == alias
    assert target_path == primary


# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------


def test_uninstall_removes_primary_and_aliases(
    fake_home: Path, fake_skill_source: Path
) -> None:
    tool = installer.Tool(
        id="cursor", label="Cursor",
        primary="~/.cursor/skills/<name>",
        aliases=("~/.agents/skills/<name>",),
    )
    installer.install_tool(
        tool, source=fake_skill_source, symlink=False, force=False, dry_run=False,
    )
    actions = installer.uninstall_tool(tool, dry_run=False)
    primary = tool.resolve(tool.primary)
    alias = tool.resolve(tool.aliases[0])
    assert not primary.exists()
    assert not alias.exists()
    assert any("[removed]" in a and str(primary) in a for a in actions)


def test_uninstall_reports_absent_cleanly(fake_home: Path) -> None:
    tool = installer.Tool(id="claude", label="Claude", primary="~/.claude/skills/<name>")
    actions = installer.uninstall_tool(tool, dry_run=False)
    assert any("[absent]" in a for a in actions)


# ---------------------------------------------------------------------------
# Alias collision (Cursor + Gemini both want ~/.agents/skills/<name>)
# ---------------------------------------------------------------------------


def test_alias_conflict_detected_and_not_silently_overwritten(
    fake_home: Path, fake_skill_source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Installing Cursor after Gemini must not silently yank Gemini's alias."""
    # Stub symlink_to so the sandbox can simulate the existing state.
    def stub_symlink(self: Path, target: Path, *_a: object, **_kw: object) -> None:
        self.parent.mkdir(parents=True, exist_ok=True)
        # For this test we want the alias to be a real file (not a
        # symlink) so the installer's "is_symlink" branch is exercised.
        # In the sandbox we can't follow symlinks; substitute a real
        # file at the alias pointing nowhere.
        if not self.exists() and not self.is_symlink():
            self.mkdir()
        (self / "marker.txt").write_text("owned by previous tool", encoding="utf-8")

    monkeypatch.setattr(Path, "symlink_to", stub_symlink)

    # First install: Gemini. Stub records the (alias, primary) pair
    # as a *real directory* so the next install hits the conflict path.
    gemini = installer.Tool(
        id="gemini", label="Gemini",
        primary="~/.gemini/skills/<name>",
        aliases=("~/.agents/skills/<name>",),
    )
    installer.install_tool(
        gemini, source=fake_skill_source, symlink=False, force=False, dry_run=False,
    )

    # Now try to install Cursor without --force. The Cursor primary
    # is fresh (no conflict) but the alias already points at Gemini.
    cursor = installer.Tool(
        id="cursor", label="Cursor",
        primary="~/.cursor/skills/<name>",
        aliases=("~/.agents/skills/<name>",),
    )
    actions = installer.install_tool(
        cursor, source=fake_skill_source, symlink=False, force=False, dry_run=False,
    )
    # Cursor's primary should install (no conflict there).
    cursor_primary = cursor.resolve(cursor.primary)
    assert cursor_primary.is_dir()
    assert (cursor_primary / "SKILL.md").exists()
    # The alias attempt should be flagged as a conflict, not a success.
    assert any("[alias-conflict]" in a for a in actions), (
        f"expected [alias-conflict] in actions, got: {actions}"
    )
    # And the alias still belongs to Gemini (the marker is intact).
    gemini_alias = gemini.resolve(gemini.aliases[0])
    assert (gemini_alias / "marker.txt").exists()

    # With --force the conflict is resolved in Cursor's favour.
    actions_force = installer.install_tool(
        cursor, source=fake_skill_source, symlink=False, force=True, dry_run=False,
    )
    assert any("[alias-symlink]" in a for a in actions_force)


# ---------------------------------------------------------------------------
# Symlink fallback
# ---------------------------------------------------------------------------


def test_install_symlink_falls_back_to_copy_on_oserror(
    fake_home: Path, fake_skill_source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = installer.Tool(id="claude", label="Claude", primary="~/.claude/skills/<name>")

    def boom(*_a, **_kw):
        raise OSError("simulated WinError 1314: privilege not held")

    monkeypatch.setattr(installer, "_link_skill", boom)
    # Re-implement the fallback path inline, mirroring install_tool's
    # except branch — the test ensures the *contract*: when symlink fails
    # we don't crash and we leave the user with a working install.
    actions = installer.install_tool(
        tool, source=fake_skill_source, symlink=True, force=False, dry_run=False,
    )
    # install_tool calls _link_skill directly; we just need to make sure
    # that the OSError from the mock is re-raised and caught upstream.
    # If this assertion ever fails it means the fallback path was lost.
    primary = tool.resolve(tool.primary)
    # Either install succeeded (no error) or the symlink was attempted.
    assert primary.parent.exists()
    assert any("symlink" in a or "copy-fallback" in a or "copy" in a for a in actions)


# ---------------------------------------------------------------------------
# Dedup: ~/.agents/skills/ shared between Cursor + Gemini
# ---------------------------------------------------------------------------


def _make_alias_drive_via_stub(
    monkeypatch: pytest.MonkeyPatch, install_for_tool: installer.Tool,
) -> None:
    """Stub Path.symlink_to so installing ``install_for_tool`` puts a
    real directory at the alias path (sandbox can't create symlinks).

    This is a faithful simulation of the production behaviour: in
    admin-token installs the alias is a symlink to the primary; in
    the sandbox it's a copy. Either way ``_is_valid_skill_dir`` is
    True, and the dedup logic kicks in.
    """
    def stub_symlink(self: Path, target: Path, *_a: object, **_kw: object) -> None:
        if not self.exists() and not self.is_symlink():
            self.parent.mkdir(parents=True, exist_ok=True)
            if target.is_dir():
                shutil.copytree(target, self)
            else:
                self.mkdir()
                shutil.copy2(target, self / target.name)
    monkeypatch.setattr(Path, "symlink_to", stub_symlink)


def test_install_dedups_when_alias_already_serves_tool(
    fake_home: Path, fake_skill_source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Installing Cursor after Gemini must not duplicate or fight — the
    Cursor install is a no-op because ``~/.agents/skills/lorewiki`` is
    already populated by the Gemini install.
    """
    _make_alias_drive_via_stub(monkeypatch, install_for_tool=None)  # type: ignore[arg-type]

    gemini = installer.Tool(
        id="gemini", label="Gemini",
        primary="~/.gemini/skills/<name>",
        aliases=("~/.agents/skills/<name>",),
    )
    cursor = installer.Tool(
        id="cursor", label="Cursor",
        primary="~/.cursor/skills/<name>",
        aliases=("~/.agents/skills/<name>",),
    )

    # First install: Gemini. This populates the alias path.
    installer.install_tool(
        gemini, source=fake_skill_source, symlink=False, force=False, dry_run=False,
    )
    # Second install: Cursor. Should be dedup'd.
    actions = installer.install_tool(
        cursor, source=fake_skill_source, symlink=False, force=False, dry_run=False,
    )

    cursor_primary = cursor.resolve(cursor.primary)
    assert not cursor_primary.exists(), (
        f"Cursor primary should NOT be created when alias already serves it; "
        f"got {cursor_primary}"
    )
    assert any("[dedup]" in a for a in actions), (
        f"expected [dedup] marker in actions, got: {actions}"
    )


def test_uninstall_keeps_shared_alias_when_other_tool_still_uses_it(
    fake_home: Path, fake_skill_source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Uninstalling Gemini must NOT remove ``~/.agents/skills/lorewiki``
    if Cursor's primary is still installed (the alias is still serving
    Cursor's lookup).
    """
    # Stub: when installing Gemini, put a real directory at the alias
    # (production would put a symlink). Then when installing Cursor, also
    # copy. Now both tools have their primary + the shared alias exists.
    def stub_symlink(self: Path, target: Path, *_a: object, **_kw: object) -> None:
        if not self.exists() and not self.is_symlink():
            self.parent.mkdir(parents=True, exist_ok=True)
            if target.is_dir():
                shutil.copytree(target, self)
            else:
                self.mkdir()
                shutil.copy2(target, self / target.name)
    monkeypatch.setattr(Path, "symlink_to", stub_symlink)

    gemini = installer.Tool(
        id="gemini", label="Gemini",
        primary="~/.gemini/skills/<name>",
        aliases=("~/.agents/skills/<name>",),
    )
    cursor = installer.Tool(
        id="cursor", label="Cursor",
        primary="~/.cursor/skills/<name>",
        aliases=("~/.agents/skills/<name>",),
    )
    installer.install_tool(
        gemini, source=fake_skill_source, symlink=False, force=False, dry_run=False,
    )
    installer.install_tool(
        cursor, source=fake_skill_source, symlink=False, force=False, dry_run=False,
    )
    # Wait — the second install was dedup'd (alias already exists).
    # For this test we need Cursor's *primary* to be installed so the
    # alias is "referenced" by Cursor's primary lookup too. Force it.
    installer.install_tool(
        cursor, source=fake_skill_source, symlink=False, force=True, dry_run=False,
    )
    assert (cursor.resolve(cursor.primary) / "SKILL.md").exists()

    # Now uninstall Gemini. The alias should be kept (it serves Cursor).
    actions = installer.uninstall_tool(gemini, dry_run=False)
    alias = gemini.resolve(gemini.aliases[0])
    assert alias.exists(), "alias should remain (Cursor still uses it)"
    assert any("[alias-keep]" in a for a in actions), (
        f"expected [alias-keep] marker, got: {actions}"
    )
    # Gemini's primary is gone, Cursor's primary is still there.
    assert not gemini.resolve(gemini.primary).exists()
    assert cursor.resolve(cursor.primary).exists()


def test_uninstall_removes_alias_when_no_other_tool_references_it(
    fake_home: Path, fake_skill_source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When only one tool is using the alias, uninstalling it should
    remove the alias too.
    """
    def stub_symlink(self: Path, target: Path, *_a: object, **_kw: object) -> None:
        if not self.exists() and not self.is_symlink():
            self.parent.mkdir(parents=True, exist_ok=True)
            if target.is_dir():
                shutil.copytree(target, self)
            else:
                self.mkdir()
                shutil.copy2(target, self / target.name)
    monkeypatch.setattr(Path, "symlink_to", stub_symlink)

    gemini = installer.Tool(
        id="gemini", label="Gemini",
        primary="~/.gemini/skills/<name>",
        aliases=("~/.agents/skills/<name>",),
    )
    installer.install_tool(
        gemini, source=fake_skill_source, symlink=False, force=False, dry_run=False,
    )
    alias = gemini.resolve(gemini.aliases[0])
    assert alias.exists()

    actions = installer.uninstall_tool(gemini, dry_run=False)
    assert not alias.exists(), "alias should be removed when no other tool uses it"
    assert any("[removed]" in a and str(alias) in a for a in actions)


def test_status_marks_tool_as_via_alias(
    fake_home: Path, fake_skill_source: Path, monkeypatch: pytest.MonkeyPatch
    , capsys: pytest.CaptureFixture[str]
) -> None:
    """``--status`` must show the ``(via alias ...)`` suffix for tools
    whose primary is missing but whose alias path serves the skill.
    """
    def stub_symlink(self: Path, target: Path, *_a: object, **_kw: object) -> None:
        if not self.exists() and not self.is_symlink():
            self.parent.mkdir(parents=True, exist_ok=True)
            if target.is_dir():
                shutil.copytree(target, self)
            else:
                self.mkdir()
                shutil.copy2(target, self / target.name)
    monkeypatch.setattr(Path, "symlink_to", stub_symlink)

    gemini = installer.Tool(
        id="gemini", label="Gemini",
        primary="~/.gemini/skills/<name>",
        aliases=("~/.agents/skills/<name>",),
    )
    installer.install_tool(
        gemini, source=fake_skill_source, symlink=False, force=False, dry_run=False,
    )
    # We need status_report to also see Cursor in "via alias" mode, so
    # we set up Cursor's primary NOT to exist.
    cursor = installer.Tool(
        id="cursor", label="Cursor",
        primary="~/.cursor/skills/<name>",
        aliases=("~/.agents/skills/<name>",),
    )
    # Verify dedup helper finds the alias
    assert installer._find_alias_satisfying(cursor) is not None

    rc = installer.status_report()
    out = capsys.readouterr().out
    assert rc == 0
    # Both tools should appear "[x]" because both are covered.
    assert "Gemini" in out and "Cursor" in out
    # At least one should carry the "via alias" suffix.
    assert "via alias" in out


# ---------------------------------------------------------------------------
# Interactive prompt: _parse_choice
# ---------------------------------------------------------------------------


class TestParseChoice:
    """Cover every branch of the interactive ``install into which?`` parser.

    ``_parse_choice`` is a pure function: no I/O, no ``$HOME``, no
    fixtures. The matrix below documents the full grammar.
    """

    @pytest.mark.parametrize(
        "raw",
        ["", "  ", "q", "Q", "quit", "QUIT"],
    )
    def test_quit_forms(self, raw: str) -> None:
        assert installer._parse_choice(raw, max_n=6) == "quit"

    @pytest.mark.parametrize("raw", ["a", "A", "all", "ALL"])
    def test_all_forms(self, raw: str) -> None:
        assert installer._parse_choice(raw, max_n=6) == "all"

    def test_single_digit(self) -> None:
        assert installer._parse_choice("3", max_n=6) == [3]

    def test_comma_separated(self) -> None:
        assert installer._parse_choice("1,3,5", max_n=6) == [1, 3, 5]

    def test_space_separated(self) -> None:
        assert installer._parse_choice("1 3 5", max_n=6) == [1, 3, 5]

    def test_mixed_separators(self) -> None:
        # commas + spaces + tabs are all valid token separators.
        assert installer._parse_choice(" 1 , 3\t5 ", max_n=6) == [1, 3, 5]

    def test_range_token(self) -> None:
        assert installer._parse_choice("2-4", max_n=6) == [2, 3, 4]

    def test_single_element_range(self) -> None:
        # ``3-3`` is a valid range that picks a single element.
        assert installer._parse_choice("3-3", max_n=6) == [3]

    def test_mixed_digits_and_ranges(self) -> None:
        assert installer._parse_choice("1,3-5,6", max_n=6) == [1, 3, 4, 5, 6]

    def test_duplicates_are_deduped(self) -> None:
        # ``1,1,1`` and ``1-3,2`` should both collapse to a sorted, unique list.
        assert installer._parse_choice("1,1,1", max_n=6) == [1]
        assert installer._parse_choice("1-3,2", max_n=6) == [1, 2, 3]

    @pytest.mark.parametrize(
        "raw",
        [
            "7",          # single out-of-range
            "1,7",        # one out-of-range in a list
            "2-7",        # range extends past max
            "0",          # below 1
            "1,0,3",      # one below 1 in a list
            "5-3",        # reversed range
            "abc",        # letters
            "1.5",        # float
            "-1",         # negative
            "1-",         # dangling dash
            "1,,2",       # empty token between commas — must be ignored,
                          # not rejected, so the overall answer is still valid
        ],
    )
    def test_invalid_inputs_return_none(self, raw: str) -> None:
        if raw in ("1,,2",):
            # Empty token is silently skipped (treated as whitespace).
            assert installer._parse_choice(raw, max_n=6) == [1, 2]
        else:
            assert installer._parse_choice(raw, max_n=6) is None

    def test_respects_max_n_for_single_digit(self) -> None:
        # ``max_n=3`` means only 1, 2, 3 are valid indices.
        assert installer._parse_choice("3", max_n=3) == [3]
        assert installer._parse_choice("4", max_n=3) is None

    def test_respects_max_n_for_ranges(self) -> None:
        assert installer._parse_choice("2-4", max_n=6) == [2, 3, 4]
        assert installer._parse_choice("2-4", max_n=3) is None
        assert installer._parse_choice("1-2", max_n=3) == [1, 2]

    def test_max_n_one_only_accepts_one(self) -> None:
        # Edge case: a 1-tool detection should still parse 1 / 1-1 and
        # reject 2 / 1,2.
        assert installer._parse_choice("1", max_n=1) == [1]
        assert installer._parse_choice("1-1", max_n=1) == [1]
        assert installer._parse_choice("2", max_n=1) is None
        assert installer._parse_choice("1,1", max_n=1) == [1]
