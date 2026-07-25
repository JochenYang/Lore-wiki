"""Internal helpers shared by the CLI command modules.

None of these are Typer callbacks or decorators themselves — they
are plain functions / data that the command modules import. Keeping
them out of :mod:`lorewiki.cli.apps` avoids a circular dependency
(``apps`` defines the Typer instances; commands import them).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from rich.table import Table

# Re-export the apps module's console so command files don't need to
# import from both ``apps`` and ``helpers`` (which is what causes
# the "two ways to import the same symbol" confusion).
from lorewiki.cli.apps import console, log
from lorewiki.config import LoreWikiConfig, discover_project_config_dir, load_config
from lorewiki.config import _deep_merge as deep_merge

# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------


def resolve_config(path_arg: str | None) -> LoreWikiConfig:
    """Build a :class:`LoreWikiConfig` honouring the optional ``--path`` argument."""
    if path_arg:
        project = Path(path_arg).expanduser().resolve()
        overrides: dict[str, Any] = {"wiki_path": str(project)}
        return load_config(project_dir=project, overrides=overrides)
    return load_config()


def discover_project_dir(cfg: LoreWikiConfig) -> Path:
    """Return the directory that should host ``.lorewiki/config.toml``."""
    if discovered := discover_project_config_dir():
        return discovered
    return cfg.wiki_path


def resolve_doc_target(doc_path: str, wiki_root: Path) -> Path:
    """Resolve a user-supplied ``doc_path`` against the wiki root.

    Absolute paths are honoured when they already live under
    ``wiki_root``; relative paths are joined under ``wiki_root``.
    Paths that resolve *outside* the wiki (including ``..`` escapes
    and absolute paths elsewhere on the filesystem) raise
    :class:`ValueError` so callers cannot accidentally write or
    delete outside the vault.

    Callers that want a second belt-and-braces check may still run
    :func:`lorewiki.cli.add._is_safe_target` on the return value.

    Used by the ``update`` and ``delete`` commands (CLI + MCP) so they
    accept the same ``doc_path`` spelling (relative to the wiki, or an
    absolute path *inside* the wiki).
    """
    raw = Path(doc_path)
    if raw.is_absolute():
        target = raw.resolve(strict=False)
    else:
        target = (wiki_root / raw).resolve(strict=False)
    try:
        root = wiki_root.resolve(strict=False)
    except OSError as exc:
        raise ValueError(f"wiki root unreadable: {wiki_root}") from exc
    # Must be a strict descendant of the wiki root (never the root itself).
    if target == root or root not in target.parents:
        raise ValueError(
            f"doc_path resolves outside wiki root: {doc_path!r} -> {target}"
        )
    return target


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def human_bytes(num: int) -> str:
    """Format a byte count as ``B / KB / MB / GB``."""
    units = ["B", "KB", "MB", "GB"]
    size = float(num)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{num} B"


def print_phase_status() -> None:
    """Helper for tests and `python -m lorewiki info` (added in later phases)."""
    table = Table(title="LoreWiki phase status", show_lines=False)
    table.add_column("Phase", style="cyan")
    table.add_column("Status", style="green")
    table.add_row("0  bootstrap / CLI skeleton", "done")
    table.add_row("1  index + BM25 search", "done")
    table.add_row("2  hierarchy + RRF fusion", "done")
    table.add_row("3  LLM integration", "done")
    table.add_row("4  cleaning + on-disk rewrite", "done")
    table.add_row("5  CLI restructure + add command", "done")
    console.print(table)


# ---------------------------------------------------------------------------
# Config (de)flattening for the `config` sub-app
# ---------------------------------------------------------------------------


def flatten_config(cfg: LoreWikiConfig) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    raw = cfg.model_dump(mode="json", exclude_none=False)

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                walk(f"{prefix}.{k}" if prefix else k, v)
        else:
            flat[prefix] = value

    walk("", raw)
    return flat


_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|secret|password|token|credential)",
    re.IGNORECASE,
)


def is_secret_config_key(key: str) -> bool:
    """True if a dotted config key looks like a secret field."""
    return bool(_SECRET_KEY_RE.search(key))


def format_value(value: Any, *, key: str | None = None) -> str:
    """Format a config value for display; redact secret keys."""
    if key is not None and is_secret_config_key(key):
        if value in (None, "", "(none)"):
            return "(none)" if value is None else ""
        return "***"
    if isinstance(value, str):
        return value
    if value is None:
        return "(none)"
    return json.dumps(value, ensure_ascii=False)


def parse_toml_literal(raw: str) -> Any:
    """Parse a CLI-provided value as a TOML right-hand-side."""
    if sys.version_info >= (3, 11):
        import tomllib as _toml  # noqa: PLC0415
    else:  # pragma: no cover
        import tomli as _toml  # noqa: PLC0415
    try:
        return _toml.loads(f"v = {raw}")["v"]
    except _toml.TOMLDecodeError:
        # Fall back to bare string.
        return raw


def unflatten(flat: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for dotted, value in flat.items():
        parts = dotted.split(".")
        cursor = out
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
    return out


def safe_load_toml(path: Path) -> dict[str, Any]:
    if sys.version_info >= (3, 11):
        import tomllib as _toml  # noqa: PLC0415
    else:  # pragma: no cover
        import tomli as _toml  # noqa: PLC0415
    try:
        return _toml.loads(path.read_text(encoding="utf-8"))
    except _toml.TOMLDecodeError:
        return {}


__all__ = [
    "console",
    "deep_merge",
    "discover_project_dir",
    "flatten_config",
    "format_value",
    "human_bytes",
    "is_secret_config_key",
    "log",
    "parse_toml_literal",
    "print_phase_status",
    "resolve_config",
    "resolve_doc_target",
    "safe_load_toml",
    "unflatten",
]
