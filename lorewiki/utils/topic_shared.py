"""Shared helpers for reading the active topic name.

Both :mod:`lorewiki.config` and :mod:`lorewiki.topic` need to consult
``~/lorewiki/current`` to discover which topic is active. They used
to duplicate the read logic (the duplication is documented in
:mod:`lorewiki.config` as "duplicated to avoid a circular import").
That workaround is no longer needed now that the relationship is
straight-line: ``config`` reads the current topic (no import of
``topic``) and ``topic`` imports from ``utils`` (which is leaf-level
in the dependency graph).

The single source of truth lives here.
"""

from __future__ import annotations

from pathlib import Path

USER_CONFIG_DIR = Path.home() / ".lorewiki"
USER_TOPICS_ROOT = USER_CONFIG_DIR / "topics"
CURRENT_FILE = USER_CONFIG_DIR / "current"


def read_current_topic() -> str | None:
    """Return the active topic name from ``~/lorewiki/current``.

    Returns ``None`` if the file is missing, empty, or unreadable.
    Never raises.
    """
    if not CURRENT_FILE.is_file():
        return None
    try:
        text = CURRENT_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


__all__ = ["CURRENT_FILE", "USER_CONFIG_DIR", "USER_TOPICS_ROOT", "read_current_topic"]
