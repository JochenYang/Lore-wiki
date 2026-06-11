"""Tests for the markdown chunker."""

from __future__ import annotations

from lorewiki.indexer.chunker import (
    chunk_markdown,
    estimate_tokens,
    split_by_h2,
)


def test_chunk_markdown_small_doc_kept_as_one_chunk() -> None:
    """A small doc (≤ max_tokens) should yield exactly one chunk with the
    full body, so LLM/RAG callers see the complete API instead of a
    truncated slice."""
    body = (
        "# wx.openChatTool(Object object)\n\n"
        "## 功能描述\n\n进入聊天工具模式。\n\n"
        "## 参数\n\n"
        "| 属性 | 类型 | 说明 |\n| --- | --- | --- |\n"
        "| roomid | string | 群聊 id |\n"
        "| chatType | number | 群聊类型 |\n\n"
        "## 示例代码\n\n"
        "```js\nwx.openChatTool({ roomid: 'x', chatType: 1 })\n```\n"
    )
    chunks = chunk_markdown(
        title="api/chattool/wx.openChatTool.md",
        body=body,
        max_tokens=800,
    )
    assert len(chunks) == 1
    chunk = chunks[0]
    # H1 is captured as the chunk's heading for breadcrumb display.
    assert chunk.heading == "wx.openChatTool(Object object)"
    assert "wx.openChatTool" in chunk.heading_path
    # The full body — including params table and code sample — is preserved.
    assert "参数" in chunk.body
    assert "示例代码" in chunk.body
    assert "wx.openChatTool" in chunk.body


def test_chunk_markdown_large_doc_still_splits_on_h2() -> None:
    """A doc that exceeds max_tokens still gets split on ``##`` boundaries."""
    # Build a doc with many large ## sections.
    long_section = "## Section A\n\n" + ("详细说明。" * 200) + "\n\n"
    long_section += "## Section B\n\n" + ("更详细说明。" * 200) + "\n\n"
    long_section += "## Section C\n\n" + ("更多说明。" * 200) + "\n"
    body = "# Big Doc\n\n" + long_section
    # max_tokens=50 forces every section over the budget.
    chunks = chunk_markdown(title="big.md", body=body, max_tokens=50)
    assert len(chunks) >= 2, "oversized doc must still be split into multiple chunks"


def test_chunk_markdown_empty_body_returns_empty() -> None:
    """Empty body shouldn't crash; yields no chunks."""
    chunks = chunk_markdown(title="empty.md", body="", max_tokens=800)
    assert chunks == []


def test_chunk_markdown_preserves_full_body_for_small_doc() -> None:
    """The full body round-trips into the single chunk, not a truncated slice."""
    body = "# api.signature()\n\n## 功能描述\n\nA short description.\n\n## 参数\n\nParam A.\n"
    chunks = chunk_markdown(title="x.md", body=body, max_tokens=800)
    assert len(chunks) == 1
    assert chunks[0].body == body.strip()


def test_split_by_h2_still_works_for_oversized() -> None:
    """Sanity: the existing H2 splitter keeps working — used by the
    large-doc path. Code fences must not be mistaken for headings."""
    body = "## Real Heading\n\n```js\n## not a heading\n```\n\n## Another\n"
    sections = split_by_h2(body)
    # Body starts with `##`, so no prelude section; two real H2 headings.
    assert len(sections) == 2
    headings = [h for h, _ in sections]
    assert "Real Heading" in headings
    assert "Another" in headings
    assert "not a heading" not in headings


def test_estimate_tokens_handles_cjk_and_ascii() -> None:
    """The heuristic must count CJK chars as 1 token each and ASCII words too."""
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello world") == 2
    # 5 CJK characters.
    assert estimate_tokens("你好世界主") == 5
    # Mixed: 2 ASCII words + 5 CJK chars (each char counts separately).
    assert estimate_tokens("hello 你好 world 再见 主") == 7
