"""Tests for the markdown cleaning pipeline."""

from __future__ import annotations

import pytest

from lorewiki.indexer.cleaning import (
    clean_heading_path,
    clean_markdown,
    clean_snippet,
    clean_title,
    compress_blank_lines,
    strip_anchor_in_heading,
    strip_boilerplate_blockquotes,
    strip_breadcrumb_prefix,
    strip_html_in_internal_links,
    strip_translation_footer,
)


# ---- strip_anchor_in_heading ----


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "# [#](#wx-foo-Object-object) wx.foo(Object object)",
            "# wx.foo(Object object)",
        ),
        (
            "## [#](#a-b) a b",
            "## a b",
        ),
        (
            "### [#](#Object-object) Object object",
            "### Object object",
        ),
        (
            "## [#](#a-b) a b\n\nbody",
            "## a b\n\nbody",
        ),
        (
            "## no anchor here",
            "## no anchor here",
        ),
    ],
)
def test_strip_anchor_in_heading(raw: str, expected: str) -> None:
    assert strip_anchor_in_heading(raw) == expected


# ---- strip_boilerplate_blockquotes ----


def test_strips_baselib_paragraph() -> None:
    text = (
        "intro line\n"
        "\n"
        "> 基础库 1.1.0 开始支持,需要兼容处理\n"
        "\n"
        "next line\n"
    )
    cleaned = strip_boilerplate_blockquotes(text)
    assert "基础库" not in cleaned
    assert "intro line" in cleaned
    assert "next line" in cleaned


def test_strips_promise_paragraph() -> None:
    text = (
        "> **以 Promise 风格 调用**: 支持\n"
        "\n"
        "> other content that should be preserved\n"
    )
    cleaned = strip_boilerplate_blockquotes(text)
    assert "Promise" not in cleaned
    assert "other content" in cleaned


def test_strips_all_wechat_platform_paragraphs() -> None:
    text = (
        "> **微信 Windows 版**: 支持\n"
        "\n"
        "> **微信 Mac 版**: 支持\n"
        "\n"
        "> **微信 鸿蒙 OS 版**: 支持\n"
        "\n"
        "## 重要章节\n"
    )
    cleaned = strip_boilerplate_blockquotes(text)
    assert "Windows" not in cleaned
    assert "Mac 版" not in cleaned
    assert "鸿蒙" not in cleaned
    assert "## 重要章节" in cleaned


def test_strips_plugin_paragraphs() -> None:
    text = (
        "> **小程序插件**: 支持,需要基础库 >= 2.1.0\n"
        "\n"
        "> 在小程序插件中使用时,只能在当前插件的页面中调用\n"
        "\n"
        "> **需要页面权限**: 当前是插件页面时,宿主小程序不能调用\n"
        "\n"
        "## 文档\n"
    )
    cleaned = strip_boilerplate_blockquotes(text)
    assert "小程序插件" not in cleaned
    assert "需要页面权限" not in cleaned
    assert "## 文档" in cleaned


def test_preserves_non_boilerplate_blockquote() -> None:
    text = "> **重要提示**: 这是用户提示,应该保留\n"
    assert "重要提示" in strip_boilerplate_blockquotes(text)


def test_preserves_regular_text() -> None:
    text = "plain text paragraph\n\nanother paragraph\n"
    assert strip_boilerplate_blockquotes(text) == text


# ---- strip_translation_footer ----


def test_strips_translation_footer() -> None:
    text = (
        "## example code\n\n"
        "```\n"
        "wx.foo()\n"
        "```\n"
        "\n"
        "The translations are provided by WeChat Translation and are for reference only. "
        "In case of any inconsistency and discrepancy between the Chinese version and the English "
        "version, the Chinese version shall prevail.Incorrect translation. "
        "[Tap to report.](javascript:;)\n"
    )
    cleaned = strip_translation_footer(text)
    assert "## example code" in cleaned
    assert "wx.foo()" in cleaned
    assert "translations are provided" not in cleaned
    assert "Tap to report" not in cleaned


def test_no_footer_unchanged() -> None:
    text = "## content\n\nno footer here.\n"
    assert strip_translation_footer(text) == text


# ---- strip_html_in_internal_links ----


def test_strips_html_from_internal_link() -> None:
    text = "see [compat](../../framework/compatibility.html)"
    cleaned = strip_html_in_internal_links(text)
    assert cleaned == "see [compat](../../framework/compatibility)"


def test_strips_html_with_anchor() -> None:
    text = "[Promise](../../framework/app-service/api.html#async-api)"
    cleaned = strip_html_in_internal_links(text)
    assert cleaned == "[Promise](../../framework/app-service/api#async-api)"


def test_preserves_external_https_link() -> None:
    text = "see [GitHub](https://github.com/foo/bar.html)"
    cleaned = strip_html_in_internal_links(text)
    assert cleaned == text


def test_preserves_external_http_link() -> None:
    text = "see [Old](http://example.com/page.html)"
    cleaned = strip_html_in_internal_links(text)
    assert cleaned == text


# ---- compress_blank_lines ----


def test_compress_blank_lines() -> None:
    assert compress_blank_lines("a\n\n\n\n\nb") == "a\n\nb"
    assert compress_blank_lines("a\n\nb") == "a\n\nb"
    assert compress_blank_lines("a\nb") == "a\nb"


# ---- clean_title ----


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("#wx.foo()", "wx.foo()"),
        ("# wx.foo()", "wx.foo()"),
        ("wx.foo()", "wx.foo()"),
        (" # trim me ", "trim me"),
        ("", ""),
    ],
)
def test_clean_title(raw: str, expected: str) -> None:
    assert clean_title(raw) == expected


# ---- clean_heading_path ----


def test_clean_heading_path() -> None:
    raw = "#wx.foo(Object object) > [#](#wx-foo-Object-object) wx.foo(Object object)"
    assert clean_heading_path(raw) == "wx.foo(Object object) > wx.foo(Object object)"


def test_clean_heading_path_strips_empty_segments() -> None:
    raw = "#wx > [#](#foo)  >  # bar"
    assert clean_heading_path(raw) == "wx > bar"


# ---- strip_breadcrumb_prefix ----


def test_strip_breadcrumb_prefix() -> None:
    text = "[title > heading]\n\nactual body content"
    assert strip_breadcrumb_prefix(text) == "actual body content"


def test_strip_breadcrumb_prefix_no_match() -> None:
    text = "actual body"
    assert strip_breadcrumb_prefix(text) == "actual body"


# ---- clean_snippet ----


def test_clean_snippet_strips_breadcrumb_and_footer() -> None:
    text = (
        "[title > heading]\n\n"
        "body content\n"
        "\n"
        "The translations are provided by WeChat Translation and are for reference only."
    )
    cleaned = clean_snippet(text)
    assert "[" not in cleaned
    assert "translations" not in cleaned
    assert "body content" in cleaned


# ---- clean_markdown (full pipeline) ----


def test_clean_markdown_full_realistic_doc() -> None:
    """End-to-end test on a realistic scraped doc fragment.

    The source file is written in UTF-8; Python 3 source files default to
    UTF-8 encoding, so literal Chinese in the source is fine.
    """
    raw = (
        "# [#](#wx-foo-Object-object) wx.foo(Object object)\n"
        "\n"
        "> 基础库 1.1.0 开始支持,需要兼容处理\n"
        "\n"
        "> **以 Promise 风格 调用**: 支持\n"
        "\n"
        "> **小程序插件**: 支持,需要基础库 >= 2.1.0\n"
        "\n"
        "> **微信 Windows 版**: 支持\n"
        "\n"
        "> **微信 Mac 版**: 支持\n"
        "\n"
        "> **微信 鸿蒙 OS 版**: 支持\n"
        "\n"
        "## [#](#功能描述) 功能描述\n"
        "\n"
        "foo 的功能描述,参考 [兼容处理](../../framework/compatibility.html)。\n"
        "\n"
        "## [#](#参数) 参数\n"
        "\n"
        "| 属性 | 类型 | 说明 |\n"
        "| --- | --- | --- |\n"
        "| id | string | 用户 id |\n"
        "\n"
        "The translations are provided by WeChat Translation and are for reference only. "
        "In case of any inconsistency and discrepancy between the Chinese version and the English "
        "version, the Chinese version shall prevail.Incorrect translation. "
        "[Tap to report.](javascript:;)\n"
    )
    cleaned = clean_markdown(raw)
    # Headings cleaned.
    assert "# wx.foo(Object object)" in cleaned
    assert "## 功能描述" in cleaned
    assert "## 参数" in cleaned
    # Boilerplate gone.
    assert "基础库" not in cleaned
    assert "小程序插件" not in cleaned
    assert "Windows" not in cleaned
    assert "Mac 版" not in cleaned
    # Footer gone.
    assert "translations are provided" not in cleaned
    assert "Tap to report" not in cleaned
    # Body preserved.
    assert "foo 的功能描述" in cleaned
    assert "| id | string | 用户 id |" in cleaned
    # .html stripped from internal links.
    assert "../../framework/compatibility)" in cleaned
    assert "../../framework/compatibility.html)" not in cleaned


def test_clean_markdown_idempotent() -> None:
    raw = (
        "# [#](#title) title\n"
        "\n"
        "> 基础库 1.1.0 开始支持\n"
        "\n"
        "body [link](../../foo.html)\n"
        "\n"
        "The translations are provided by WeChat Translation\n"
    )
    once = clean_markdown(raw)
    twice = clean_markdown(once)
    assert once == twice


def test_clean_markdown_empty() -> None:
    assert clean_markdown("") == ""
    assert clean_markdown("   \n\n  ") == ""
    # Trailing newline preserved.
    assert clean_markdown("body\n").endswith("\n")
    assert clean_markdown("body").endswith("body")


def test_clean_markdown_preserves_code_blocks() -> None:
    raw = (
        "## example code\n"
        "\n"
        "```\n"
        "wx.foo({\n"
        "  id: \'x\'\n"
        "})\n"
        "```\n"
        "\n"
        "Trailing text.\n"
    )
    cleaned = clean_markdown(raw)
    assert "wx.foo({" in cleaned
    assert "id: \'x\'" in cleaned
    assert "Trailing text." in cleaned
