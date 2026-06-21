"""Markdown chunking with ``##`` boundaries + token-budget fallback.

The default chunker:

1. Splits the body on ``##`` (level-2) headings, treating everything before
   the first ``##`` as a leading chunk (so files without ``##`` headings still
   index to a single chunk).
2. Each chunk records ``heading_path`` — a breadcrumb of the level-2 heading
   (and the document title), e.g. ``"User Auth > POST /login"``. The path is
   prepended to the chunk content so FTS matches on heading terms.
3. Chunks that exceed ``max_tokens`` are further split on blank-line boundaries
   with ``overlap_tokens`` of leading context carried into the next slice. We
   deliberately don't break inside fenced code blocks.
4. Tiny chunks (below ``min_chars``) are merged with the next sibling chunk so
   we don't waste rows on stub headings like ``## TODO``.

Token counting uses a fast heuristic: ``len(text)`` for CJK + ``len(text.split())``
for whitespace-separated runs. Within ~30% of the real BPE count, which is
plenty for sizing decisions.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from lorewiki.indexer.patterns import CODE_FENCE_RE, H1_RE, H2_RE


@dataclass(slots=True)
class Chunk:
    chunk_index: int
    heading: str | None
    heading_path: str
    body: str

    def with_breadcrumb(self) -> str:
        """Return body prefixed by the heading path (improves FTS recall)."""
        if not self.heading_path:
            return self.body
        return f"[{self.heading_path}]\n\n{self.body}"


_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def estimate_tokens(text: str) -> int:
    """Heuristic token count: CJK chars + whitespace-separated words."""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    ascii_runs = _ASCII_TOKEN_RE.findall(text)
    return cjk + len(ascii_runs)


def split_by_h2(body: str) -> list[tuple[str | None, str]]:
    """Split ``body`` on ``##`` boundaries.

    Returns a list of ``(heading, content)`` tuples where ``heading`` is None
    for the prelude before the first ``##``.
    """
    lines = body.splitlines(keepends=True)
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    in_code = False
    for line in lines:
        if CODE_FENCE_RE.match(line.lstrip()):
            in_code = not in_code
            sections[-1][1].append(line)
            continue
        if not in_code:
            match = H2_RE.match(line)
            if match:
                sections.append((match.group(1).strip(), []))
                continue
        sections[-1][1].append(line)
    return [(h, "".join(lines)) for h, lines in sections if "".join(lines).strip() or h]


def _split_paragraphs_preserving_code(text: str) -> list[str]:
    """Split on blank lines but never break inside fenced code blocks."""
    paragraphs: list[str] = []
    buf: list[str] = []
    in_code = False
    for line in text.splitlines(keepends=True):
        if CODE_FENCE_RE.match(line.lstrip()):
            in_code = not in_code
            buf.append(line)
            continue
        if not in_code and line.strip() == "":
            if buf:
                paragraphs.append("".join(buf))
                buf = []
            continue
        buf.append(line)
    if buf:
        paragraphs.append("".join(buf))
    return paragraphs


def _slice_oversized(
    section: str, *, max_tokens: int, overlap_tokens: int
) -> list[str]:
    """Slice an oversized section into pieces respecting blank-line boundaries."""
    paragraphs = _split_paragraphs_preserving_code(section)
    pieces: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for para in paragraphs:
        ptokens = estimate_tokens(para)
        if current and current_tokens + ptokens > max_tokens:
            pieces.append("\n\n".join(current))
            # Carry overlap from the tail of the previous piece.
            tail: list[str] = []
            tail_tokens = 0
            for back in reversed(current):
                tail_tokens += estimate_tokens(back)
                tail.insert(0, back)
                if tail_tokens >= overlap_tokens:
                    break
            current = list(tail)
            current_tokens = tail_tokens
        current.append(para)
        current_tokens += ptokens
    if current:
        pieces.append("\n\n".join(current))
    return pieces


def _extract_h1(body: str) -> str | None:
    """Return the first ``#`` heading of ``body`` (without the leading ``#``).

    Frontmatter is already stripped by the parser, so the first ``#`` line
    in ``body`` is the H1.
    """
    match = H1_RE.search(body)
    return match.group(1).strip() if match else None


def chunk_markdown(
    *,
    title: str,
    body: str,
    max_tokens: int = 800,
    overlap_tokens: int = 100,
    min_chars: int = 40,
) -> list[Chunk]:
    """Produce :class:`Chunk` records for one document body.

    Small documents (total token count ≤ ``max_tokens``) are kept as a
    single chunk so downstream retrieval surfaces the **complete** doc —
    callers asking "how do I call wx.foo?" get the API signature, params,
    and example in one hit instead of three isolated fragments.
    """
    # Small-doc fast path: keep the whole document as one chunk. We still
    # surface the H1 as the chunk's heading so it appears in the
    # heading_path breadcrumb and shows up in CLI output.
    if body.strip() and estimate_tokens(body) <= max_tokens:
        h1 = _extract_h1(body)
        return [
            Chunk(
                chunk_index=0,
                heading=h1,
                heading_path=" > ".join(p for p in (title, h1) if p),
                body=body.strip(),
            )
        ]

    sections = split_by_h2(body)
    raw_chunks: list[tuple[str | None, str]] = []
    for heading, content in sections:
        text = content.strip()
        if not text:
            continue
        for piece in _slice_oversized(
            text, max_tokens=max_tokens, overlap_tokens=overlap_tokens
        ) or [text]:
            raw_chunks.append((heading, piece))

    merged = _merge_tiny(raw_chunks, min_chars=min_chars)

    chunks: list[Chunk] = []
    for idx, (heading, content) in enumerate(merged):
        crumb_parts = [title]
        if heading:
            crumb_parts.append(heading)
        heading_path = " > ".join(p for p in crumb_parts if p)
        chunks.append(
            Chunk(
                chunk_index=idx,
                heading=heading,
                heading_path=heading_path,
                body=content,
            )
        )
    return chunks


def _merge_tiny(
    raw_chunks: list[tuple[str | None, str]], *, min_chars: int
) -> list[tuple[str | None, str]]:
    if not raw_chunks:
        return raw_chunks
    out: list[tuple[str | None, str]] = []
    for heading, content in raw_chunks:
        if out and len(content) < min_chars:
            prev_heading, prev_content = out[-1]
            merged_content = prev_content.rstrip() + "\n\n"
            if heading:
                merged_content += f"### {heading}\n\n"
            merged_content += content
            out[-1] = (prev_heading, merged_content)
        else:
            out.append((heading, content))
    return out


def iter_chunks(chunks: Iterable[Chunk]) -> Iterable[tuple[int, str, str, str]]:
    """Iterate as ``(chunk_index, heading, heading_path, body_with_breadcrumb)``."""
    for ch in chunks:
        yield ch.chunk_index, ch.heading or "", ch.heading_path, ch.with_breadcrumb()


__all__ = [
    "Chunk",
    "chunk_markdown",
    "estimate_tokens",
    "iter_chunks",
    "split_by_h2",
]
