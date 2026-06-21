"""Tests for unified regex patterns."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def patterns_module():
    """Load patterns module directly to avoid __init__.py chain."""
    spec = importlib.util.spec_from_file_location(
        "patterns",
        Path(__file__).parent.parent / "lorewiki" / "indexer" / "patterns.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_h1_re_matches_heading(patterns_module):
    assert patterns_module.H1_RE.search("# Hello World").group(1) == "Hello World"


def test_h1_re_multiline(patterns_module):
    text = "Some text\n# Heading\nMore text"
    assert patterns_module.H1_RE.search(text).group(1) == "Heading"


def test_h2_re_matches_heading(patterns_module):
    assert patterns_module.H2_RE.search("## Section Title").group(1) == "Section Title"


def test_code_fence_re_matches_triple_backtick(patterns_module):
    assert patterns_module.CODE_FENCE_RE.match("```") is not None


def test_code_fence_re_matches_with_language(patterns_module):
    assert patterns_module.CODE_FENCE_RE.match("```python") is not None


def test_code_fence_re_no_match_for_regular_text(patterns_module):
    assert patterns_module.CODE_FENCE_RE.match("not code") is None


def test_code_fence_re_matches_after_lstrip(patterns_module):
    """Test that CODE_FENCE_RE works with lstrip as used in chunker.py."""
    assert patterns_module.CODE_FENCE_RE.match("  ```".lstrip()) is not None
