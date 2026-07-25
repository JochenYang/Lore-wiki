"""Cross-platform skill installer — wheel-internal copy.

This module is the **runtime** version of ``skills/install.py``. Both
modules intentionally implement the same Tool catalog and the same
``_parse_choice`` grammar; ``skills/install.py`` is for developers
who clone the repository, while this one ships inside the wheel so
that a user who installed ``lorewiki`` from PyPI can run
``lorewiki install`` without first cloning the repo.

Source of truth for the tool catalog lives here (``TOOLS``). The
repo-side ``skills/install.py`` is kept independent on purpose:
``skills/install.py`` is part of the source checkout / dev workflow
and tests live in ``tests/test_skill_installer.py``; the wheel
inherits the same logic at install time without the cross-import
that would make ``lorewiki install`` depend on the repo tree.

Differences from ``skills/install.py``:

- The wheel has no notion of "the source tree" — we use
  ``importlib.resources`` to read the bundled ``SKILL.md`` from
  ``lorewiki.data.skill_template``.
- The wheel install is **copy-only** (no symlink mode) because
  symlink semantics on Windows without Developer Mode are
  unreliable, and the wheel can't ship a Windows-aware symlink
  fallback policy cleanly.
- No ``--all-known`` / "ignore detection" flag: the wheel-side
  ``install`` is meant to be safe-by-default, only installing where
  the tool's own config root already exists.
"""
from __future__ import annotations

import contextlib
import os
import re
import sys
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Final

SKILL_NAME: Final[str] = "lorewiki"

# Source of truth: ``lorewiki.data.skill_template.SKILL.md`` is
# bundled inside the wheel (see ``pyproject.toml`` ``[tool.hatch.build
# .targets.wheel].include``). The dev-tree ``skills/lorewiki/SKILL.md``
# is the canonical upstream; the wheel copy must be re-synced when
# the dev copy changes (a test enforces the two are byte-identical).
_WHEEL_SKILL_PACKAGE: Final[str] = "lorewiki.data.skill_template"
_WHEEL_SKILL_FILE: Final[str] = "SKILL.md"


def _read_skill_template() -> str:
    """Read the bundled ``SKILL.md`` from the wheel.

    Falls back to a hard error if the data file is missing — this
    is a wheel-build configuration mistake (the package data was
    not included in ``pyproject.toml``).
    """
    try:
        return resources.files(_WHEEL_SKILL_PACKAGE).joinpath(
            _WHEEL_SKILL_FILE
        ).read_text(encoding="utf-8")
    except (ModuleNotFoundError, FileNotFoundError) as exc:
        msg = (
            f"bundled skill template not found: "
            f"{_WHEEL_SKILL_PACKAGE}/{_WHEEL_SKILL_FILE} ({exc}). "
            "This is a wheel-build error — check pyproject.toml's "
            "[tool.hatch.build.targets.wheel].include list."
        )
        raise FileNotFoundError(msg) from exc


# ---------------------------------------------------------------------------
# Tool catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Tool:
    """One supported AI tool's install target and aliases."""

    id: str
    label: str
    primary: str
    aliases: tuple[str, ...] = ()

    def resolve(self, path_template: str) -> Path:
        """Expand ``<name>`` + ``$HOME``/``~``/``$XDG_*`` env vars.

        ``os.path.expandvars`` is platform-asymmetric: it expands
        ``$VAR`` (POSIX) on Unix and ``%VAR%`` (cmd.exe) on Windows
        — but never both. Since the templates use the POSIX form
        (``$XDG_CONFIG_HOME`` etc.) and the goal is "XDG if set, else
        ``~/.config``", we expand on POSIX, and on Windows we
        detect the un-expanded ``$VAR`` and substitute
        ``$HOME/.config`` (or ``.codex``/``.gemini``) by hand.
        """
        s = path_template.replace("<name>", SKILL_NAME)
        s = os.path.expandvars(s)
        if any(needle in s for needle in ("$XDG_CONFIG_HOME", "$CODEX_HOME", "$GEMINI_HOME")):
            home = str(Path.home())
            s = s.replace("$XDG_CONFIG_HOME", f"{home}/.config")
            s = s.replace("$CODEX_HOME", f"{home}/.codex")
            s = s.replace("$GEMINI_HOME", f"{home}/.gemini")
        s = os.path.expanduser(s)
        return Path(s).resolve()


# Mirrors the catalog in ``skills/install.py``. If you edit one,
# edit the other — ``tests/test_skill_installer_wheel.py`` enforces
# equality of the visible-id set.
#
# ``primary`` is kept as a *raw* path template with ``$VAR`` placeholders
# rather than ``os.path.expandvars(os.environ.get(...))`` evaluated at
# module-import time. ``Tool.resolve`` runs ``os.path.expandvars`` on
# every call, so the env is read fresh — important for tests that
# monkey-patch ``XDG_CONFIG_HOME`` *after* the module is imported
# (and for runners that have a non-default env we want to honour
# *now*, not at import time).
TOOLS: Final[tuple[Tool, ...]] = (
    Tool(
        id="opencode",
        label="opencode",
        primary="$XDG_CONFIG_HOME/opencode/skills/<name>/SKILL.md",
    ),
    Tool(
        id="claude",
        label="Claude Code",
        primary="~/.claude/skills/<name>/SKILL.md",
    ),
    Tool(
        id="codex",
        label="Codex CLI",
        primary="$CODEX_HOME/skills/<name>/SKILL.md",
    ),
    Tool(
        id="cursor",
        label="Cursor",
        primary="~/.cursor/skills/<name>/SKILL.md",
        # Cursor also auto-discovers ~/.agents/skills/ (interop path).
        aliases=("~/.agents/skills/<name>/SKILL.md",),
    ),
    Tool(
        id="gemini",
        label="Gemini CLI",
        primary="$GEMINI_HOME/skills/<name>/SKILL.md",
        aliases=("~/.agents/skills/<name>/SKILL.md",),
    ),
    Tool(
        id="antigravity",
        label="Google Antigravity",
        primary="~/.gemini/antigravity/skills/<name>/SKILL.md",
    ),
    # Extra interop / third-party agent roots commonly present on
    # developer machines. Detected only when the tool config root
    # already exists (same safety rule as the rest of the catalog).
    Tool(
        id="agents",
        label="Agents interop (~/.agents)",
        primary="~/.agents/skills/<name>/SKILL.md",
    ),
    Tool(
        id="joycode",
        label="JoyCode",
        primary="~/.joycode/skills/<name>/SKILL.md",
    ),
)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _parent_exists(path: Path) -> bool:
    """True if the tool's *config root* exists (three levels above the SKILL.md).

    For ``~/.config/opencode/skills/lorewiki/SKILL.md`` we check
    ``~/.config/opencode/`` — the directory the tool itself creates
    on first launch. Going further up would land on ``$HOME`` /
    ``C:\\`` which always exist and would mark every tool as
    installed.
    """
    return path.parent.parent.parent.exists()


def detect_installed_tools() -> list[Tool]:
    """Return the subset of ``TOOLS`` whose skills dir is plausibly reachable."""
    return [t for t in TOOLS if _parent_exists(t.resolve(t.primary))]


# ---------------------------------------------------------------------------
# Interactive prompt parser (multi-select, ranges, ``a``, ``q``)
# ---------------------------------------------------------------------------


def _parse_choice(raw: str, max_n: int) -> list[int] | str | None:
    """Parse the interactive ``install into which?`` answer.

    Returns one of:

    - ``list[int]``  — 1-based indices of the chosen tools, in ascending
      order with duplicates removed.
    - ``"all"``       — install every detected tool.
    - ``"quit"``      — user wants to exit without installing.
    - ``None``        — input is invalid; caller should error out.

    Accepted syntax (case-insensitive, whitespace stripped):

    - ``""`` / ``q`` / ``quit``        → ``"quit"``
    - ``a`` / ``all``                  → ``"all"``
    - ``3``                            → ``[3]``
    - ``1,3,5`` or ``1 3 5``            → ``[1, 3, 5]``
    - ``2-4``                          → ``[2, 3, 4]``
    - ``1,3-5,6`` (mixed)              → ``[1, 3, 4, 5, 6]``

    Out-of-range numbers (anything outside ``1..max_n``), empty
    selections, malformed tokens, and reversed ranges all return
    ``None``.
    """
    c = raw.strip().lower()
    if c in ("", "q", "quit"):
        return "quit"
    if c in ("a", "all"):
        return "all"
    result: set[int] = set()
    for token in re.split(r"[,\s]+", c):
        if not token:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", token)
        if m is None:
            return None
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        if start < 1 or end < 1 or start > max_n or end > max_n or start > end:
            return None
        result.update(range(start, end + 1))
    return sorted(result) if result else None


def prompt_for_targets(detected: list[Tool], input_fn=input) -> list[Tool] | None:
    """Interactive multi-select prompt.

    Returns the chosen tools, or ``None`` if the user quits /
    provides invalid input. ``input_fn`` is injectable for tests.
    """
    if not detected:
        print("no AI tools detected on this machine.", file=sys.stderr)
        return None
    print("Detected tools on this machine:")
    for i, tool in enumerate(detected, 1):
        print(f"  {i}. {tool.label}  -> {tool.resolve(tool.primary)}")
    print("  a. all of the above")
    print("  q. quit")
    choice = input_fn(
        "install into which? [a / 1 / 1,3,5 / 1 3 5 / 2-4 / q]: "
    )
    parsed = _parse_choice(choice, len(detected))
    if parsed == "quit":
        return None
    if parsed == "all":
        return detected
    if parsed is None:
        print("invalid choice", file=sys.stderr)
        return None
    assert isinstance(parsed, list)
    return [detected[i - 1] for i in parsed]


# ---------------------------------------------------------------------------
# Install / uninstall primitives
# ---------------------------------------------------------------------------


def _looks_like_lorewiki_skill(text: str) -> bool:
    """True if ``text`` is (or was) a LoreWiki skill, not an unrelated file.

    Used to auto-upgrade stale installs after a package bump without
    clobbering a hand-edited non-skill file at the same path.
    """
    head = text.lstrip()[:800]
    if not head.startswith("---"):
        return False
    # Frontmatter name field (YAML) — tolerate spacing variants.
    return bool(re.search(r"(?m)^name:\s*lorewiki\s*$", head))


def _install_one_file(
    target: Path,
    skill_text: str,
    *,
    overwrite: bool,
    alias: bool = False,
) -> str:
    """Write one skill file; return a single status line for the user log."""
    tag = " (alias)" if alias else ""
    if target.exists() and not overwrite:
        try:
            existing = target.read_text(encoding="utf-8")
        except OSError as exc:
            return f"[skip] {target}{tag} (read failed: {exc})"
        if existing == skill_text:
            return f"[skip] {target}{tag} (up-to-date)"
        if not _looks_like_lorewiki_skill(existing):
            return (
                f"[skip] {target}{tag} "
                f"(exists; pass --force to overwrite non-skill content)"
            )
        # Stale lorewiki skill from an older package — upgrade in place.
        try:
            target.write_text(skill_text, encoding="utf-8")
        except OSError as exc:
            return f"[skip] {target}{tag} (write failed: {exc})"
        return f"[ok]   updated {target}{tag}"
    try:
        target.write_text(skill_text, encoding="utf-8")
    except OSError as exc:
        return f"[skip] {target}{tag} (write failed: {exc})"
    return f"[ok]   wrote {target}{tag}"


def install_skill(
    tool: Tool,
    *,
    skill_text: str | None = None,
    overwrite: bool = False,
) -> list[str]:
    """Copy the bundled ``SKILL.md`` to the tool's primary path (and aliases).

    Returns human-readable action lines.

    Default policy (no ``--force``):

    - missing → write
    - byte-identical to wheel template → skip ``up-to-date``
    - existing LoreWiki skill (frontmatter ``name: lorewiki``) but
      different text → **auto-upgrade** (package bumps refresh agents)
    - other content at the path → skip (protect user edits); ``--force``
      overwrites

    Each target is wrapped so a locked skills directory cannot abort the
    rest of the fan-out. Targets are files ``…/SKILL.md``. Legacy
    single-file alias layouts are cleaned up so ``mkdir`` does not fail.
    """
    if skill_text is None:
        skill_text = _read_skill_template()
    primary = tool.resolve(tool.primary)
    primary.parent.mkdir(parents=True, exist_ok=True)
    actions: list[str] = [
        _install_one_file(primary, skill_text, overwrite=overwrite, alias=False)
    ]

    for alias_tmpl in tool.aliases:
        alias = tool.resolve(alias_tmpl)
        if alias == primary:
            continue
        # Clean up the legacy single-file layout (e.g.
        # ``~/.agents/skills/lorewiki`` as a file, not a dir) so
        # the new ``mkdir`` doesn't fail because a parent path
        # component is a file.
        if alias.parent.exists() and not alias.parent.is_dir():
            try:
                alias.parent.unlink()
                actions.append(
                    f"[rm]   {alias.parent} (legacy single-file layout)"
                )
            except OSError as exc:
                actions.append(
                    f"[skip] {alias.parent} (legacy unlink failed: {exc})"
                )
                continue
        alias.parent.mkdir(parents=True, exist_ok=True)
        actions.append(
            _install_one_file(alias, skill_text, overwrite=overwrite, alias=True)
        )
    return actions


def uninstall_skill(tool: Tool) -> list[str]:
    """Remove the skill from the tool's primary path and aliases.

    Each target is wrapped in its own ``try/except OSError`` for the
    same reason as :func:`install_skill`: a locked directory or
    read-only mount should not abort the rest of the uninstall.

    Also handles the legacy single-file layout (e.g. an alias at
    ``~/.agents/skills/<name>`` written as a file by 0.2.5-0.2.9)
    by unlinking that file too, so ``lorewiki install --uninstall``
    leaves a clean slate.
    """
    actions: list[str] = []
    for tmpl in (tool.primary, *tool.aliases):
        target = tool.resolve(tmpl)
        if target.exists() or target.is_symlink():
            try:
                target.unlink()
            except OSError as exc:
                actions.append(f"[skip] {target} (unlink failed: {exc})")
                continue
            actions.append(f"[rm]   {target}")
            # Clean up the now-empty parent dir if we can.
            with contextlib.suppress(OSError):
                target.parent.rmdir()
        else:
            actions.append(f"[skip] {target} (not present)")
    return actions


# ---------------------------------------------------------------------------
# Status report (one-liner per tool, ``[x]`` / ``[ ]``)
# ---------------------------------------------------------------------------


def _skill_installed(tool: Tool) -> bool:
    """True if the tool's primary OR any alias already has the skill."""
    return any(tool.resolve(tmpl).exists() for tmpl in (tool.primary, *tool.aliases))


def status_report() -> str:
    """Return a human-readable status block for ``lorewiki install --status``."""
    lines = ["LoreWiki skill status", "=" * 60]
    for tool in TOOLS:
        primary = tool.resolve(tool.primary)
        marker = "[x]" if _skill_installed(tool) else "[ ]"
        lines.append(f"  {marker} {tool.label:<18} {primary}")
        for alias_tmpl in tool.aliases:
            alias = tool.resolve(alias_tmpl)
            a_marker = "[x]" if alias.exists() else "[ ]"
            lines.append(f"  {a_marker}   alias           {alias}")
    # Hint if the bundled template is readable from the wheel — this
    # is also a soft smoke test of the package-data wiring.
    try:
        _read_skill_template()
    except FileNotFoundError as exc:
        lines.append("")
        lines.append(f"  ERROR: {exc}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# High-level entry point used by the CLI
# ---------------------------------------------------------------------------


def run(
    *,
    tool_ids: list[str] | None = None,
    install_all: bool = False,
    uninstall: bool = False,
    force: bool = False,
    show_status: bool = False,
    input_fn=input,
) -> int:
    """Single entry point used by ``lorewiki install``.

    ``tool_ids`` is a list of canonical Tool.id values (e.g.
    ``["opencode", "claude"]``). When ``None`` and ``install_all``
    is ``False``, the function falls back to the interactive
    prompt. Returns the process exit code.
    """
    if show_status:
        print(status_report())
        return 0

    if tool_ids is not None:
        by_id = {t.id: t for t in TOOLS}
        unknown = [i for i in tool_ids if i not in by_id]
        if unknown:
            print(
                f"unknown --tool ids: {unknown}; "
                f"valid: {sorted(by_id)}",
                file=sys.stderr,
            )
            return 2
        targets: list[Tool] = [by_id[i] for i in tool_ids]
    elif install_all:
        targets = detect_installed_tools()
        if not targets:
            print("no AI tools detected on this machine.", file=sys.stderr)
            return 1
    else:
        targets = prompt_for_targets(detect_installed_tools(), input_fn=input_fn) or []
        if not targets:
            return 0

    try:
        skill_text = _read_skill_template()
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"source: bundled {_WHEEL_SKILL_PACKAGE}/{_WHEEL_SKILL_FILE}")
    for tool in targets:
        print(f"\n[{tool.label}]")
        actions = (
            uninstall_skill(tool)
            if uninstall
            else install_skill(tool, skill_text=skill_text, overwrite=force)
        )
        for line in actions:
            print(line)
    return 0
