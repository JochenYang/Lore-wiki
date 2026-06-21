"""Markdown frontmatter parsing and metadata extraction.

This module is intentionally thin: it produces a normalised
:class:`ParsedDocument` that downstream chunking / hierarchy modules can
consume without knowing about ``python-frontmatter`` internals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import frontmatter

from lorewiki.indexer.patterns import H1_RE


@dataclass(slots=True)
class ParsedDocument:
    """Result of parsing a Markdown file.

    Attributes:
        path: relative path used as a stable identifier (e.g. ``api/user/auth.md``).
        title: best-effort title (frontmatter > first ``#`` heading > filename).
        module: optional logical module path (frontmatter or first dir component).
        tags: optional tag list from frontmatter.
        owner: optional owner string from frontmatter.
        body: Markdown body **without** frontmatter.
        metadata: full frontmatter dict.
    """

    path: str
    title: str
    body: str
    module: str | None = None
    tags: list[str] = field(default_factory=list)
    owner: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def parse_markdown(file_path: Path, *, rel_to: Path | None = None) -> ParsedDocument:
    """Parse ``file_path`` and return a :class:`ParsedDocument`.

    ``rel_to`` controls the ``path`` field; if given, ``file_path`` is made
    relative to that directory (POSIX separators) so paths stay stable across
    machines.
    """
    raw = file_path.read_text(encoding="utf-8")
    post = frontmatter.loads(raw)
    metadata = dict(post.metadata or {})
    body = post.content

    if rel_to is not None:
        try:
            rel = file_path.relative_to(rel_to)
        except ValueError:
            rel = file_path
        rel_path = rel.as_posix()
    else:
        rel_path = file_path.as_posix()

    title = _extract_title(metadata, body, file_path)
    module = _normalise_module(metadata, rel_path)
    tags = _normalise_tags(metadata)
    owner = metadata.get("owner")
    if owner is not None and not isinstance(owner, str):
        owner = str(owner)

    return ParsedDocument(
        path=rel_path,
        title=title,
        body=body,
        module=module,
        tags=tags,
        owner=owner,
        metadata=metadata,
    )


def _extract_title(metadata: dict[str, Any], body: str, file_path: Path) -> str:
    if isinstance(metadata.get("title"), str) and metadata["title"].strip():
        return metadata["title"].strip()
    match = H1_RE.search(body)
    if match:
        return match.group(1).strip()
    return file_path.stem


def _normalise_module(metadata: dict[str, Any], rel_path: str) -> str | None:
    raw = metadata.get("module")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().strip("/")
    # Fall back to the first directory component of the relative path.
    parts = rel_path.split("/")
    if len(parts) > 1:
        return "/".join(parts[:-1])
    return None


def _normalise_tags(metadata: dict[str, Any]) -> list[str]:
    raw = metadata.get("tags")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [t.strip() for t in raw.split(",") if t.strip()]
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if str(t).strip()]
    return []


__all__ = ["ParsedDocument", "parse_markdown"]
