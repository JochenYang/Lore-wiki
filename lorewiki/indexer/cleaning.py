"""Markdown cleaning for scraped wiki content.

Scraped Markdown (e.g. from the WeChat miniprogram docs) carries a lot of
chrome that pollutes search indices and makes `heading_path` ugly:

* ``# [#](#wx-foo-Object-object) wx.foo(Object object)`` — anchor markup the
  scraper put around every heading.
* ``> 基础库 1.1.0 开始支持…`` and ``> 微信 Windows 版：支持`` etc. — metadata
  blockquotes that are repeated on *every* page, polluting the hierarchy
  summary and making almost every node match a query containing common
  terms like "文档", "framework", "ability".
* ``The translations are provided by WeChat Translation…`` — translation
  footer present on every doc, also contains "framework" via cross-links.
* ``[compatibility](../../framework/compatibility.html)`` — internal links
  still carry the ``.html`` extension that breaks Obsidian/Logseq
  resolution.
* ``#wx.foo()`` — frontmatter title that picks up the leading ``#`` from
  the H1.

The cleaning functions below are pure, idempotent, and conservative: they
*remove* obvious boilerplate and *normalise* links, but never rewrite the
author's content. They run at **index time** (not on the disk files), so
the on-disk vault remains a faithful copy of the scrape and Obsidian can
display whatever the user wants.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# ---- heading anchors --------------------------------------------------------

# Matches ``#  [#](#anchor-name)   Some Title  `` at the start of a line.
# We accept 1-6 leading ``#`` and trailing horizontal whitespace. Using
# ``[ \t]*$`` (not ``\s*$``) so we don't accidentally eat the line
# terminator when ``re.MULTILINE`` is set.
ANCHOR_HEADING_RE = re.compile(
    r"^(#{1,6})\s*\[\#\]\(#[^)]*\)\s*(.+?)[ \t]*$",
    re.MULTILINE,
)


def strip_anchor_in_heading(text: str) -> str:
    """Remove ``[#](#anchor)`` from headings: ``# [#](#foo) title`` -> ``# title``."""
    return ANCHOR_HEADING_RE.sub(r"\1 \2", text)


# ---- boilerplate blockquotes ------------------------------------------------

# These patterns match the *text* of a single blockquote paragraph (the ``>``
# prefix already stripped). The line that *starts* with the marker is enough
# to identify the paragraph as boilerplate; everything inside that blockquote
# gets dropped along with it.
_BOILERPLATE_MARKERS: tuple[str, ...] = (
    r"基础库\s*\d+\.\d+",  # 基础库 1.1.0 开始支持 / 基础库 2.13.0 开始支持
    r"\*\*以\s*\[?\s*Promise",  # 以 [Promise 风格… 调用
    r"\*\*以\s*Promise",  # alternative (no brackets)
    r"\*\*需要页面权限\*\*",  # 需要页面权限
    r"\*\*小程序插件\*\*\s*[::]",  # 小程序插件：支持 / 小程序插件：支持，需要…
    r"在小程序插件中使用时",  # 在小程序插件中使用时，只能在当前插件的页面中调用
    r"在插件页面时",  # 在插件页面时，宿主小程序不能调用该接口
    r"\*\*微信\s*Windows\s*版\*\*",  # 微信 Windows 版：支持
    r"\*\*微信\s*Mac\s*版\*\*",  # 微信 Mac 版：支持
    r"\*\*微信\s*鸿蒙\s*OS\s*版\*\*",  # 微信 鸿蒙 OS 版：支持
)

_BOILERPLATE_RES = tuple(re.compile(p) for p in _BOILERPLATE_MARKERS)


def _split_blocks(text: str) -> list[list[str]]:
    """Split ``text`` into blocks separated by one or more blank lines.

    Returns a list of line-lists; each inner list is a "block" (paragraph,
    blockquote, code fence, etc.) and the original blank lines are not
    preserved. This makes it easy to drop an entire block at a time.
    """
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.split("\n"):
        if line.strip() == "":
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _is_blockquote_block(block: Iterable[str]) -> bool:
    """A block is a blockquote if every non-blank line starts with ``>``."""
    return all(line.lstrip().startswith(">") for line in block)


def _blockquote_text(block: Iterable[str]) -> str:
    """Return the textual content of a blockquote block, prefix stripped."""
    return "\n".join(
        re.sub(r"^>\s?", "", line).strip() for line in block if line.strip()
    ).strip()


def _is_boilerplate_blockquote(block: list[str]) -> bool:
    text = _blockquote_text(block)
    if not text:
        return False
    return any(p.search(text) for p in _BOILERPLATE_RES)


def strip_boilerplate_blockquotes(text: str) -> str:
    """Remove blockquote paragraphs that match the boilerplate markers above.

    A "blockquote paragraph" is a contiguous run of ``>``-prefixed lines
    separated from neighbours by a blank line. The whole paragraph is
    dropped (so the surrounding blank lines collapse naturally). A
    trailing newline is preserved when the input had one.
    """
    had_trailing_newline = text.endswith("\n")
    blocks = _split_blocks(text)
    kept: list[list[str]] = []
    for block in blocks:
        if _is_blockquote_block(block) and _is_boilerplate_blockquote(block):
            continue
        kept.append(block)
    out = _join_blocks(kept)
    if had_trailing_newline and not out.endswith("\n"):
        out += "\n"
    return out


def _join_blocks(blocks: list[list[str]]) -> str:
    """Inverse of :func:`_split_blocks` — joins with single blank lines."""
    parts: list[str] = []
    for i, block in enumerate(blocks):
        if i > 0:
            parts.append("")
        parts.extend(block)
    return "\n".join(parts)


def _strip_trailing_blank_lines(text: str) -> tuple[str, int]:
    """Return ``(text_without_trailing_blank_lines, n_blank)``.

    The block joiner above cannot know whether the original ended with a
    blank line, so we track it here and re-append it after :func:`clean_markdown`
    runs. Markdown convention is to end files with a single trailing
    newline, so we always re-add at least one.
    """
    n = 0
    while text.endswith("\n\n"):
        text = text[:-1]
        n += 1
    return text, n


# ---- translation footer ------------------------------------------------------

# Footer from the bilingual WeChat docs that pollutes the tail of every doc.
TRANSLATION_FOOTER_RE = re.compile(
    r"^[^\n]*The translations are provided by WeChat Translation.*$",
    re.MULTILINE | re.DOTALL,
)


def strip_translation_footer(text: str) -> str:
    """Drop everything from the translation footer marker onward."""
    match = TRANSLATION_FOOTER_RE.search(text)
    if match is None:
        return text
    return text[: match.start()].rstrip()


# ---- internal link normalisation --------------------------------------------

# Matches ``](...html)`` or ``](...html#anchor)``. We strip the ``.html`` only
# if the URL does NOT start with ``http://`` or ``https://``.
INTERNAL_HTML_LINK_RE = re.compile(
    r"\]\(([^)]*?)\.html((?:\#|\\#)[^)]*)?\)"
)


def strip_html_in_internal_links(text: str) -> str:
    """Strip ``.html`` from internal Markdown links so Obsidian can resolve them.

    External links (``http://...``, ``https://...``) are left alone.
    Anchor fragments (``#some-id``) are preserved.
    """
    def _replace(match: re.Match[str]) -> str:
        url = match.group(1)
        anchor = match.group(2) or ""
        if url.startswith("http://") or url.startswith("https://"):
            return match.group(0)
        return f"]({url}{anchor})"

    return INTERNAL_HTML_LINK_RE.sub(_replace, text)


# ---- blank-line compression -------------------------------------------------

# Three or more consecutive newlines collapse to exactly two (``\n\n``).
_BLANK_LINE_RUN_RE = re.compile(r"\n{3,}")


def compress_blank_lines(text: str) -> str:
    """Collapse runs of 3+ blank lines to a single blank line."""
    return _BLANK_LINE_RUN_RE.sub("\n\n", text)


# ---- top-level entry point --------------------------------------------------


def clean_markdown(text: str) -> str:
    """Apply the full cleaning pipeline to a Markdown body.

    Idempotent: running it twice is equivalent to running it once (assuming
    no new patterns sneak in via the footer / anchor steps, which the
    regexes are written to avoid). Preserves a single trailing newline
    (Markdown convention) when the input had one.
    """
    if not text:
        return text
    had_trailing_newline = text.endswith("\n")
    text = strip_translation_footer(text)
    text = strip_boilerplate_blockquotes(text)
    text = strip_anchor_in_heading(text)
    text = strip_html_in_internal_links(text)
    text = compress_blank_lines(text)
    text = text.strip()
    if had_trailing_newline:
        text += "\n"
    return text


# ---- title & heading_path helpers -------------------------------------------

_LEADING_HASH_RE = re.compile(r"^#\s*")


def clean_title(title: str) -> str:
    """Strip a leading ``#`` (and any whitespace) from a title string.

    Frontmatter titles in scraped content often look like ``"#wx.foo()"``
    or ``" #wx.foo() "`` — that leading ``#`` is the Markdown H1 marker
    the scraper copied in. We first strip surrounding whitespace, then
    peel off any ``#`` prefix (with optional whitespace after it).
    """
    if not title:
        return ""
    return _LEADING_HASH_RE.sub("", title.strip()).strip()


def clean_heading_path(heading_path: str) -> str:
    """Strip ``[#](#anchor)`` and any leading ``#`` from heading path segments.

    Heading paths look like ``"#wx.foo() > [#](#wx-foo) wx.foo()"``; the
    leading ``#`` is the frontmatter title's stale H1 marker, and the
    ``[#](#anchor)`` is the scraper's anchor pattern. We clean each
    segment individually then re-join.
    """
    if not heading_path:
        return ""
    parts = []
    for seg in heading_path.split(">"):
        seg = _ANCHOR_SEGMENT_RE.sub(_ANCHOR_SEGMENT_REPL, seg).strip()
        seg = clean_title(seg)
        if seg:
            parts.append(seg)
    return " > ".join(parts)


_ANCHOR_SEGMENT_RE = re.compile(r"^\s*\[\#\]\(#[^)]*\)\s*(.+?)[ \t]*$")
_ANCHOR_SEGMENT_REPL = r"\1"


# ---- snippet post-processing ------------------------------------------------

# Breadcrumb prefix added by ``chunker.Chunk.with_breadcrumb()`` — looks like
# ``[some heading path]\n\n``.
_BREADCRUMB_PREFIX_RE = re.compile(r"^\[[^\[\]]*\]\n\n")


def strip_breadcrumb_prefix(text: str) -> str:
    """Strip the ``[heading_path]\\n\\n`` breadcrumb prefix from a chunk body.

    The breadcrumb is added by :meth:`chunker.Chunk.with_breadcrumb` so
    FTS5 matches on heading terms. The same content is exposed in the
    ``heading_path`` field of the :class:`SearchHit`, so embedding it in
    the snippet is redundant.
    """
    if not text:
        return text
    return _BREADCRUMB_PREFIX_RE.sub("", text, count=1).lstrip()


def clean_snippet(text: str) -> str:
    """Apply the snippet-only post-processing pipeline.

    Strips the breadcrumb prefix and the translation footer (if any
    somehow leaked through to the indexed content). The full body cleaning
    is the indexer's job, not the retriever's; this function is a safety
    net for the on-the-wire representation.
    """
    if not text:
        return text
    text = strip_breadcrumb_prefix(text)
    text = strip_translation_footer(text)
    return text.rstrip()


# ---- whole-file cleaning (for `lorewiki clean` on disk) --------------------

# Matches a leading YAML frontmatter block: ``---\n...\n---\n`` at the very
# start of the file. We keep the delimiters in the captured group so we can
# re-emit the frontmatter verbatim.
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_FRONTMATTER_TITLE_RE = re.compile(
    r"^(\s*title:\s+)(\"[^\"]*\"|'[^']*'|[^\n#]+)(\s*(?:#.*)?)$",
    re.MULTILINE,
)


def _clean_frontmatter_title(fm_text: str) -> str:
    """Strip a leading ``#`` from the ``title:`` field inside a frontmatter block.

    YAML quoting is preserved: ``title: "#wx.foo()"`` becomes
    ``title: "wx.foo()"``. Unquoted values are also handled.
    """

    def _replace(match: re.Match[str]) -> str:
        prefix, raw_value, suffix = match.group(1), match.group(2), match.group(3)
        quote = ""
        value = raw_value
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            quote = value[0]
            value = value[1:-1]
        cleaned = clean_title(value)
        return f"{prefix}{quote}{cleaned}{quote}{suffix}"

    return _FRONTMATTER_TITLE_RE.sub(_replace, fm_text)


def split_frontmatter(text: str) -> tuple[str, str]:
    """Split a Markdown file into ``(frontmatter, body)``.

    The frontmatter is the leading ``---\\n...\\n---\\n`` block (including
    the delimiter lines and the trailing newline). The body is everything
    after. Files without a frontmatter return ``("", text)``.
    """
    match = FRONTMATTER_RE.match(text)
    if match is None:
        return "", text
    return match.group(0), text[match.end():]


def clean_markdown_file(text: str) -> str:
    """Clean a complete Markdown file (frontmatter + body) for ``lorewiki clean``.

    - Frontmatter block (if present) is preserved verbatim except for the
      ``title:`` field, which gets a leading-``#`` stripped.
    - Body is passed through :func:`clean_markdown` but the leading blank
      line between ``---`` and the first body heading is preserved
      (markdown convention — Obsidian breaks if you elide it).
    - Trailing newline is preserved.

    Idempotent: running twice on already-cleaned text is a no-op.
    """
    fm, body = split_frontmatter(text)

    # Peel off the leading whitespace of the body (the conventional blank
    # line between frontmatter and the first heading) so we can re-attach
    # it after ``clean_markdown`` (which strips leading whitespace).
    leading_ws = ""
    body_content = body
    while body_content and body_content[0] in ("\n", " ", "\t"):
        leading_ws += body_content[0]
        body_content = body_content[1:]

    cleaned_body = clean_markdown(body_content)
    if not cleaned_body.endswith("\n") and (body.endswith("\n") or body == ""):
        cleaned_body += "\n"

    cleaned_fm = _clean_frontmatter_title(fm) if fm else ""
    if cleaned_fm and not cleaned_fm.endswith("\n"):
        cleaned_fm += "\n"
    return cleaned_fm + leading_ws + cleaned_body


__all__ = [
    "clean_heading_path",
    "clean_markdown",
    "clean_markdown_file",
    "clean_snippet",
    "clean_title",
    "compress_blank_lines",
    "split_frontmatter",
    "strip_anchor_in_heading",
    "strip_boilerplate_blockquotes",
    "strip_breadcrumb_prefix",
    "strip_html_in_internal_links",
    "strip_translation_footer",
]
