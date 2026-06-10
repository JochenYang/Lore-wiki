"""Tests for the Markdown parser + chunker."""

from __future__ import annotations

from pathlib import Path

from lorewiki.indexer.chunker import (
    chunk_markdown,
    estimate_tokens,
    split_by_h2,
)
from lorewiki.indexer.parser import parse_markdown


def write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_parse_extracts_frontmatter(tmp_path: Path) -> None:
    p = write(
        tmp_path,
        "auth.md",
        """---
title: Auth API
module: api/user
tags: [auth, jwt]
owner: identity-team
---

# Body H1

Some content.
""",
    )
    parsed = parse_markdown(p, rel_to=tmp_path)
    assert parsed.title == "Auth API"
    assert parsed.module == "api/user"
    assert parsed.tags == ["auth", "jwt"]
    assert parsed.owner == "identity-team"
    assert parsed.path == "auth.md"
    assert "Some content." in parsed.body


def test_parse_falls_back_to_h1_when_no_title(tmp_path: Path) -> None:
    p = write(tmp_path, "x.md", "# First Heading\n\nBody.\n")
    parsed = parse_markdown(p, rel_to=tmp_path)
    assert parsed.title == "First Heading"


def test_parse_module_defaults_to_directory(tmp_path: Path) -> None:
    p = write(tmp_path, "a/b/c.md", "# c\n\nBody\n")
    parsed = parse_markdown(p, rel_to=tmp_path)
    assert parsed.module == "a/b"


def test_tags_string_form_normalised(tmp_path: Path) -> None:
    p = write(
        tmp_path,
        "t.md",
        "---\ntitle: T\ntags: 'one, two, three'\n---\n\nBody",
    )
    parsed = parse_markdown(p, rel_to=tmp_path)
    assert parsed.tags == ["one", "two", "three"]


def test_split_by_h2_keeps_prelude() -> None:
    body = "Intro paragraph.\n\n## First\n\nSection one.\n\n## Second\n\nSection two."
    parts = split_by_h2(body)
    headings = [h for h, _ in parts]
    assert headings == [None, "First", "Second"]


def test_split_by_h2_ignores_h2_inside_code_blocks() -> None:
    body = (
        "Intro.\n\n## Real\n\nReal section.\n\n```\n## NotASection\n```\n\n## Second\nbody"
    )
    parts = split_by_h2(body)
    headings = [h for h, _ in parts]
    assert headings == [None, "Real", "Second"]


def test_chunk_markdown_basic() -> None:
    # Each section needs to exceed min_chars (40 by default) so the merger
    # doesn't fuse them together.
    body = (
        "Intro section with enough content to remain on its own.\n\n"
        "## A\n\n" + ("Sentence about A. " * 5) + "\n\n"
        "## B\n\n" + ("Sentence about B. " * 5) + "\n"
    )
    chunks = chunk_markdown(title="Doc", body=body)
    assert len(chunks) >= 2
    crumbs = [c.heading_path for c in chunks]
    assert any("A" in c for c in crumbs)
    assert any("B" in c for c in crumbs)
    for c in chunks:
        assert c.heading_path.startswith("Doc")
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_chunk_oversized_section_is_split() -> None:
    big = "Paragraph one.\n\n" + ("Lots of content here. " * 200)
    chunks = chunk_markdown(
        title="Big",
        body=f"## Section\n\n{big}",
        max_tokens=100,
        overlap_tokens=20,
    )
    assert len(chunks) > 1
    for c in chunks:
        # Overlapping slices preserve the same heading.
        assert c.heading == "Section"


def test_chunk_tiny_section_merged_into_neighbour() -> None:
    body = "## Big\n\n" + ("Sentence. " * 50) + "\n\n## TODO\n\nx"
    chunks = chunk_markdown(title="Doc", body=body, min_chars=40)
    # The trailing ``## TODO`` is below min_chars so it must fuse with ``Big``.
    assert "TODO" in chunks[-1].body or any("TODO" in c.body for c in chunks)
    # Total count must be lower than the naive 2.
    assert len(chunks) == 1


def test_estimate_tokens_counts_cjk_and_ascii() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello world") == 2
    # 4 CJK chars + 1 ascii word.
    assert estimate_tokens("用户认证 api") == 5


def test_chunker_with_breadcrumb_includes_heading_path() -> None:
    body = "## Heading X\n\ncontent."
    chunks = chunk_markdown(title="T", body=body)
    assert chunks[0].with_breadcrumb().startswith("[T > Heading X]")
