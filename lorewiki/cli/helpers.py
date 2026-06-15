"""Internal helpers shared by the CLI command modules.

None of these are Typer callbacks or decorators themselves — they
are plain functions / data that the command modules import. Keeping
them out of :mod:`lorewiki.cli.apps` avoids a circular dependency
(``apps`` defines the Typer instances; commands import them).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from rich.table import Table

# Re-export the apps module's console so command files don't need to
# import from both ``apps`` and ``helpers`` (which is what causes
# the "two ways to import the same symbol" confusion).
from lorewiki.cli.apps import console, log
from lorewiki.config import LoreWikiConfig, load_config

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
    cwd_candidate = Path.cwd() / ".lorewiki" / "config.toml"
    if cwd_candidate.exists():
        return Path.cwd()
    return cfg.wiki_path


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


def format_value(value: Any) -> str:
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


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
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
    "log",
    "parse_toml_literal",
    "print_phase_status",
    "resolve_config",
    "safe_load_toml",
    "unflatten",
]
