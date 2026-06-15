"""Cross-platform installer for the LoreWiki agent skill.

Each AI coding tool ships its own "skills" directory convention:

  | Tool          | User-level skills dir                               |
  |---------------|-----------------------------------------------------|
  | opencode      | $XDG_CONFIG_HOME/opencode/skills/<name>             |
  |               |   default: ~/.config/opencode/skills/<name>          |
  | Claude Code   | ~/.claude/skills/<name>                             |
  | Codex CLI     | $CODEX_HOME/skills/<name>                           |
  |               |   default: ~/.codex/skills/<name>                   |
  | Cursor        | ~/.cursor/skills/<name>                             |
  |               |   alias: ~/.agents/skills/<name> (also read)        |
  | Gemini CLI    | $GEMINI_HOME/skills/<name>                          |
  |               |   default: ~/.gemini/skills/<name>                  |
  |               |   alias: ~/.agents/skills/<name> (also read)        |
  | Antigravity   | ~/.gemini/antigravity/skills/<name>                 |

The ``SKILL.md`` is identical across tools (frontmatter fields ``name`` and
``description`` are universal; tool-specific fields like Claude's
``disable-model-invocation`` or Cursor's ``paths`` are simply ignored by
other tools, not rejected), so we install one source to all targets.

Usage::

    python skills/install.py                 # detect installed tools, prompt
    python skills/install.py --all           # install into every detected tool
    python skills/install.py --tool opencode,claude,codex
    python skills/install.py --symlink       # dev: live edits visible
    python skills/install.py --status        # show current install state
    python skills/install.py --uninstall --tool claude
    python skills/install.py --dry-run       # preview without touching disk

Design goals
------------

1. **One script, all OSes** — Python stdlib only, no ``osascript`` / ``reg``
   / PowerShell-specific tricks. Tested on Windows + macOS + Linux.
2. **Detect, don't decide** — the script reports which tools it *can* see
   (their config dir exists) and lets the user pick. ``--all`` is a
   convenience for users who want to fan out blindly.
3. **Symlink fallback** — symlink mode is preferred for dev, but on Windows
   without Developer Mode the symlink call will fail; the script degrades
   to a copy and tells the user why.
4. **Alias symlinks** — when installing to Cursor or Gemini we also create
   a symlink at ``~/.agents/skills/<name>`` pointing back, because both
   tools also read from that interop path.
"""
from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SKILL_NAME = "lorewiki"

# Resolve source path relative to *this* file, not cwd, so the script works
# no matter where the user invokes it from. ``__file__`` is
# ``skills/install.py``; source is the sibling ``skills/lorewiki/`` dir.
SCRIPT_DIR = Path(__file__).resolve().parent
SOURCE_DIR = SCRIPT_DIR / SKILL_NAME


@dataclass(frozen=True)
class Tool:
    """One supported AI tool's install target and aliases."""

    id: str            # canonical id used in --tool flag
    label: str         # human-friendly display name
    primary: str       # primary user-level path template (use <name>)
    aliases: tuple[str, ...] = ()  # additional paths to symlink to the primary

    def resolve(self, path_template: str) -> Path:
        """Expand ``<name>`` + ``$HOME``/``~``/``$XDG_*`` env vars to a Path."""
        s = path_template.replace("<name>", SKILL_NAME)
        # Honour XDG / CODEX_HOME / GEMINI_HOME when set, otherwise default.
        # We expandvars *after* replacing <name> so the variable name is
        # never confused with the literal "<name>".
        s = os.path.expandvars(s)
        s = os.path.expanduser(s)
        return Path(s).resolve()


# Tool catalog. Add new tools here; the installer auto-discovers them.
TOOLS: tuple[Tool, ...] = (
    Tool(
        id="opencode",
        label="opencode",
        primary=os.environ.get("XDG_CONFIG_HOME", "~/.config")
        + "/opencode/skills/<name>",
    ),
    Tool(
        id="claude",
        label="Claude Code",
        primary="~/.claude/skills/<name>",
    ),
    Tool(
        id="codex",
        label="Codex CLI",
        primary=os.environ.get("CODEX_HOME", "~/.codex") + "/skills/<name>",
    ),
    Tool(
        id="cursor",
        label="Cursor",
        primary="~/.cursor/skills/<name>",
        # Cursor also auto-discovers ~/.agents/skills/ (interop path). One
        # symlink means the skill is registered in both name spaces.
        aliases=("~/.agents/skills/<name>",),
    ),
    Tool(
        id="gemini",
        label="Gemini CLI",
        primary=os.environ.get("GEMINI_HOME", "~/.gemini") + "/skills/<name>",
        aliases=("~/.agents/skills/<name>",),
    ),
    Tool(
        id="antigravity",
        label="Google Antigravity",
        # Antigravity is intentionally separate from ~/.gemini/skills/ even
        # though Gemini uses the same parent — its loader is path-specific.
        primary="~/.gemini/antigravity/skills/<name>",
    ),
)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _parent_exists(path: Path) -> bool:
    """True if the *config root* of the tool exists.

    For ``~/.config/opencode/skills/lorewiki`` we check
    ``~/.config/opencode/`` (two levels up from the resolved path). That
    one level is the "config root" — the directory the tool itself creates
    on first launch. Going further up the tree would land on ``$HOME`` or
    ``C:\\``, which always exist, and would mark every tool as installed.
    """
    return path.parent.parent.exists()


def detect_installed_tools() -> list[Tool]:
    """Return the subset of TOOLS whose skills dir is plausibly reachable."""
    found: list[Tool] = []
    for tool in TOOLS:
        if _parent_exists(tool.resolve(tool.primary)):
            found.append(tool)
    return found


# ---------------------------------------------------------------------------
# Install / uninstall
# ---------------------------------------------------------------------------


def _copy_skill(target: Path, source: Path) -> None:
    """Copy ``source`` (a skill directory) to ``target`` recursively."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        if target.is_symlink():
            target.unlink()
        else:
            shutil.rmtree(target)
    shutil.copytree(source, target)


def _link_skill(target: Path, source: Path) -> bool:
    """Symlink ``target`` -> ``source``. Return True on success.

    On Windows without Developer Mode or admin, ``symlink_to`` raises
    ``OSError(WinError 1314)`` ("A required privilege is not held by the
    client"). The caller should fall back to a copy in that case.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        if target.is_symlink():
            target.unlink()
        else:
            shutil.rmtree(target)
    target.symlink_to(source, target_is_directory=True)
    return True


def _remove_skill(target: Path) -> bool:
    """Remove a previously installed skill directory or symlink.

    Returns True if something was actually removed.
    """
    if not target.exists() and not target.is_symlink():
        return False
    if target.is_symlink():
        target.unlink()
    else:
        shutil.rmtree(target)
    return True


# ---------------------------------------------------------------------------
# Dedup: the ~/.agents/skills/ interop path
# ---------------------------------------------------------------------------
#
# Cursor and Gemini *both* auto-discover ``~/.agents/skills/lorewiki/`` in
# addition to their own ``~/.cursor/skills/`` / ``~/.gemini/skills/``. So
# when the user installs lorewiki for one of them, the other is also
# covered — we should not silently re-install or, worse, fight over the
# alias. The helpers below let ``install_tool`` / ``uninstall_tool`` /
# ``status_report`` reason about that shared resource without hard-coding
# the cursor-vs-gemini detail at the call site.


def _is_valid_skill_dir(path: Path) -> bool:
    """True if ``path`` is a directory (or symlink-to-directory) that
    contains a SKILL.md with non-empty body. We use this as the
    "serves the skill" check — it does *not* verify it's our exact
    SKILL.md, because the user may have edited it (symlink mode) or
    forked the install.
    """
    try:
        target = path.resolve() if path.is_symlink() else path
    except (OSError, RuntimeError):
        return False
    if not target.is_dir():
        return False
    skill_md = target / "SKILL.md"
    if not skill_md.is_file():
        return False
    try:
        return skill_md.stat().st_size > 0
    except OSError:
        return False


def _find_alias_satisfying(tool: Tool) -> Path | None:
    """Return the first alias path that already contains a valid skill
    install. Used to short-circuit ``install_tool`` when one tool is
    already covered by the shared interop path.
    """
    for alias_tmpl in tool.aliases:
        alias = tool.resolve(alias_tmpl)
        if _is_valid_skill_dir(alias):
            return alias
    return None


def _is_alias_referenced_by_other_tools(alias_path: Path, *, exclude_tool_id: str) -> bool:
    """True if some *other* tool in TOOLS also uses ``alias_path`` as
    one of its aliases *and* its primary path is still present.

    Used by ``uninstall_tool`` to avoid yanking the shared
    ``~/.agents/skills/lorewiki`` out from under a second tool that
    still depends on it.

    Why "primary" and not "primary or alias": if a second tool has
    *not* installed its own primary, it's not actually a real user of
    the alias — the alias is a leftover from a previous uninstall. We
    would otherwise refuse to clean up a stale alias forever. Requiring
    a real primary to count as "referencing" is the right gate.
    """
    resolved_alias = alias_path.resolve()
    for other in TOOLS:
        if other.id == exclude_tool_id:
            continue
        for other_alias_tmpl in other.aliases:
            try:
                other_alias = other.resolve(other_alias_tmpl)
            except (OSError, RuntimeError):
                continue
            if other_alias.resolve() != resolved_alias:
                continue
            other_primary = other.resolve(other.primary)
            if _is_valid_skill_dir(other_primary):
                return True
    return False


def install_tool(  # branched by symlink/dry-run/force/alias/dedup paths
    tool: Tool,
    *,
    source: Path,
    symlink: bool,
    force: bool,
    dry_run: bool,
) -> list[str]:
    """Install (or re-install) the skill for a single tool.

    Returns a list of human-readable action descriptions for the reporter.

    Dedup: if ``primary`` is missing but the tool's *alias* path
    (e.g. ``~/.agents/skills/lorewiki``) already contains a valid
    SKILL.md (because the user installed a different tool that
    shares that interop path), the install is a no-op for this tool
    — we still register an alias symlink only if no other tool
    "owns" the existing content. See ``_find_alias_satisfying``.
    """
    actions: list[str] = []
    primary = tool.resolve(tool.primary)

    if primary.exists() or primary.is_symlink():
        if not force:
            actions.append(f"  [skip] {primary} (exists; pass --force to overwrite)")
            return actions
        actions.append(f"  [overwrite] {primary}")
    elif not force and (serving_alias := _find_alias_satisfying(tool)) is not None:
        # Cursor and Gemini both read ~/.agents/skills/. If the user
        # already installed via the other tool, this tool is covered
        # by the shared alias. Don't re-install, don't recreate the
        # symlink — just record what happened.
        actions.append(
            f"  [dedup] {tool.label} served by existing alias "
            f"{serving_alias} (shared ~/.agents/skills/ interop path); "
            f"no action needed."
        )
        return actions

    if dry_run:
        actions.append(f"  [dry-run] would {'symlink' if symlink else 'copy'} "
                       f"{source} -> {primary}")
    elif symlink:
        try:
            _link_skill(primary, source)
            actions.append(f"  [symlink] {primary} -> {source}")
        except OSError as exc:
            # Windows without Developer Mode: 1314, ERROR_PRIVILEGE_NOT_HELD.
            # Fall back so the user still gets a working install.
            _copy_skill(primary, source)
            actions.append(
                f"  [copy-fallback] {primary} (symlink failed: {exc})"
            )
    else:
        _copy_skill(primary, source)
        actions.append(f"  [copy] {primary} (from {source})")

    # Aliases: for tools that also read from ~/.agents/skills/, make sure
    # both name spaces resolve. We use *symlink* even in copy mode because
    # the alias is a thin indirection — no benefit to duplicating bytes.
    #
    # Collision guard: if the alias path already exists and resolves to
    # a *different* primary (e.g. the user installed Gemini first which
    # created ``~/.agents/skills/lorewiki -> ~/.gemini/skills/lorewiki``,
    # and now we're installing Cursor whose alias target is
    # ``~/.cursor/skills/lorewiki``), don't silently overwrite it. The
    # user should ``--uninstall --tool gemini`` first or use ``--force``.
    for alias_tmpl in tool.aliases:
        alias = tool.resolve(alias_tmpl)
        existing = alias.is_symlink() or alias.exists()
        if existing:
            try:
                resolves_to_primary = alias.resolve() == primary.resolve()
            except (OSError, RuntimeError):
                resolves_to_primary = False
            if not resolves_to_primary:
                if not force:
                    target_hint = ""
                    if alias.is_symlink():
                        with contextlib.suppress(OSError):
                            target_hint = f" (-> {alias.readlink()})"
                    actions.append(
                        f"  [alias-conflict] {alias}{target_hint} already "
                        f"belongs to a different tool; not overwriting with "
                        f"{primary}. Use --force to take over, or uninstall "
                        f"the other tool first."
                    )
                    continue
                if dry_run:
                    actions.append(
                        f"  [dry-run] would replace alias {alias} -> {primary}"
                    )
                    continue
                if alias.is_symlink():
                    alias.unlink()
                else:
                    shutil.rmtree(alias)
        if dry_run:
            actions.append(f"  [dry-run] would symlink alias {alias} -> {primary}")
            continue
        try:
            alias.parent.mkdir(parents=True, exist_ok=True)
            alias.symlink_to(primary, target_is_directory=True)
            actions.append(f"  [alias-symlink] {alias} -> {primary}")
        except OSError as exc:
            actions.append(
                f"  [alias-skip] {alias} (symlink failed: {exc})"
            )
    return actions


def uninstall_tool(tool: Tool, *, dry_run: bool) -> list[str]:
    actions: list[str] = []
    primary = tool.resolve(tool.primary)
    if not (primary.exists() or primary.is_symlink()):
        actions.append(f"  [absent] {primary}")
    elif dry_run:
        actions.append(f"  [dry-run] would remove {primary}")
    else:
        _remove_skill(primary)
        actions.append(f"  [removed] {primary}")

    for alias_tmpl in tool.aliases:
        alias = tool.resolve(alias_tmpl)
        if not (alias.exists() or alias.is_symlink()):
            actions.append(f"  [absent] {alias}")
            continue
        # Reference-counted: don't yank the shared interop path out
        # from under another tool that still depends on it.
        if _is_alias_referenced_by_other_tools(
            alias, exclude_tool_id=tool.id
        ):
            actions.append(
                f"  [alias-keep] {alias} (also used by another tool; "
                f"uninstall that one first, or pass --force)"
            )
            continue
        if dry_run:
            actions.append(f"  [dry-run] would remove {alias}")
        else:
            _remove_skill(alias)
            actions.append(f"  [removed] {alias}")
    return actions


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def status_report() -> int:
    """Print which tools have the skill installed and exit 0.

    A tool is considered "installed" if either its primary path is
    present, *or* one of its alias paths is present (the latter is
    the dedup case: Cursor covered by ``~/.agents/skills/`` from a
    Gemini install, or vice versa).
    """
    print("LoreWiki skill status")
    print("=" * 60)
    if not SOURCE_DIR.exists():
        print(f"  ERROR: source not found at {SOURCE_DIR}", file=sys.stderr)
        return 1
    for tool in TOOLS:
        primary = tool.resolve(tool.primary)
        primary_ok = _is_valid_skill_dir(primary)
        serving_alias = _find_alias_satisfying(tool) if not primary_ok else None
        present = primary_ok or (serving_alias is not None)
        marker = "[x]" if present else "[ ]"
        suffix = ""
        if primary_ok and primary.is_symlink():
            suffix = f"  -> {primary.readlink()}"
        elif serving_alias is not None:
            suffix = f"  (via alias {serving_alias})"
        print(f"  {marker} {tool.label:<18} {primary}{suffix}")
        for alias_tmpl in tool.aliases:
            alias = tool.resolve(alias_tmpl)
            a_present = _is_valid_skill_dir(alias)
            a_marker = "[x]" if a_present else "[ ]"
            a_suffix = ""
            if a_present and alias.is_symlink():
                a_suffix = f"  -> {alias.readlink()}"
            print(f"  {a_marker}   alias           {alias}{a_suffix}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_tool_list(raw: str | None) -> list[Tool] | None:
    if raw is None:
        return None
    ids = [s.strip() for s in raw.split(",") if s.strip()]
    by_id = {t.id: t for t in TOOLS}
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        print(f"unknown --tool ids: {unknown}", file=sys.stderr)
        print(f"valid: {sorted(by_id)}", file=sys.stderr)
        sys.exit(2)
    return [by_id[i] for i in ids]


def main(argv: list[str] | None = None) -> int:  # CLI dispatch table
    parser = argparse.ArgumentParser(
        description="Install / uninstall the LoreWiki agent skill for "
        "multiple AI coding tools.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n"
        "  python skills/install.py --all\n"
        "  python skills/install.py --tool opencode,claude --symlink\n"
        "  python skills/install.py --uninstall --tool cursor\n"
        "  python skills/install.py --status\n",
    )
    parser.add_argument(
        "--tool", default=None,
        help="comma-separated tool ids (default: prompt). ids: "
        + ", ".join(t.id for t in TOOLS),
    )
    parser.add_argument(
        "--all", action="store_true",
        help="install into every detected tool without prompting",
    )
    parser.add_argument(
        "--symlink", action="store_true",
        help="symlink instead of copy (developer workflow; live edits)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="overwrite existing install at target path",
    )
    parser.add_argument(
        "--uninstall", action="store_true",
        help="remove the skill from the target tool directories",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="print where the skill is currently installed and exit",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="print actions without touching the filesystem",
    )
    args = parser.parse_args(argv)

    if args.status:
        return status_report()

    if not SOURCE_DIR.exists():
        print(f"ERROR: source skill dir not found: {SOURCE_DIR}", file=sys.stderr)
        return 1

    # Determine the target set.
    if args.tool is not None:
        targets = _parse_tool_list(args.tool)
    elif args.all:
        targets = detect_installed_tools()
        if not targets:
            print("no AI tools detected on this machine.", file=sys.stderr)
            print("hint: pass --tool to specify manually, "
                  "or open one of the tools at least once so its config "
                  "directory is created.", file=sys.stderr)
            return 1
    else:
        detected = detect_installed_tools()
        if not detected:
            print("no AI tools detected on this machine.")
            print("  pass --tool to install anyway, or use --all with --force.")
            return 1
        print("Detected tools on this machine:")
        for i, tool in enumerate(detected, 1):
            print(f"  {i}. {tool.label}  -> {tool.resolve(tool.primary)}")
        print("  a. all of the above")
        print("  q. quit")
        choice = input("install into which? [1/a/q]: ").strip().lower()
        if choice in ("q", ""):
            return 0
        if choice in ("a", "all"):
            targets = detected
        else:
            try:
                idx = int(choice) - 1
                targets = [detected[idx]]
            except (ValueError, IndexError):
                print("invalid choice", file=sys.stderr)
                return 2

    assert targets is not None
    print(f"source: {SOURCE_DIR}")
    verb = "uninstall" if args.uninstall else ("symlink" if args.symlink else "copy")
    print(f"mode:   {verb}{' (dry-run)' if args.dry_run else ''}")
    for tool in targets:
        print(f"\n[{tool.label}]")
        if args.uninstall:
            actions = uninstall_tool(tool, dry_run=args.dry_run)
        else:
            actions = install_tool(
                tool,
                source=SOURCE_DIR,
                symlink=args.symlink,
                force=args.force,
                dry_run=args.dry_run,
            )
        for line in actions:
            print(line)

    # Sanity check for the CLI: warn if lorewiki itself is missing.
    if not args.uninstall and shutil.which("lorewiki") is None:
        print("\nwarning: `lorewiki` is not on your PATH yet.", file=sys.stderr)
        print("  install it with:  uv tool install --editable . \\", file=sys.stderr)
        print("      --with fastapi --with 'uvicorn[standard]' --with mcp",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
