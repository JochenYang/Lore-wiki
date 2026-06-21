"""Unified regex patterns for markdown parsing."""

from __future__ import annotations

import re

# Matches H1 headings: # Title
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)

# Matches H2 headings: ## Title
H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)

# Matches fenced code blocks
CODE_FENCE_RE = re.compile(r"^```")

__all__ = ["CODE_FENCE_RE", "H1_RE", "H2_RE"]
