"""Unit tests for the LoreWiki MCP server (``lorewiki.mcp.server``).

These tests exercise the three MCP tools (``search`` / ``show`` / ``tree``)
by directly awaiting the decorated async handlers. They do NOT spin up a
real stdio MCP transport — that level of integration is left to manual
smoke tests with an actual MCP client (Claude Desktop, Cursor, …).

The fixture seeds a small wiki on disk, writes a ``.lorewiki/config.toml``
the server's ``load_config()`` can resolve, and patches the module-level
config-path constants so the no-argument ``load_config()`` call inside
``call_tool`` finds the test index instead of the developer's real
``~/lorewiki`` vault.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Skip all tests in this module if the optional 'mcp' package is not installed.
pytest.importorskip("mcp", reason="mcp package not installed (optional dependency)")

import lorewiki.config as _config_module
import lorewiki.utils.topic_shared as _topic_shared
from lorewiki.config import LoreWikiConfig, save_config
from lorewiki.indexer import build_index
from lorewiki.mcp.server import call_tool, list_tools

# ---------------------------------------------------------------------------
# Fixtures: hermetic config isolation + wiki seeding
# ---------------------------------------------------------------------------


def _seed_wiki(root: Path) -> None:
    """Create a two-doc wiki with a cross-link for the edges table.

    ``api/auth.md`` links to ``../patterns/retry.md`` so the ``show``
    tool's ``related_docs`` payload has something to surface.
    """
    (root / "api").mkdir(parents=True)
    (root / "patterns").mkdir(parents=True)
    (root / "api" / "auth.md").write_text(
        "---\n"
        "title: Auth\n"
        "module: api\n"
        "type: API\n"
        "---\n\n"
        "# Auth\n\n"
        "The login endpoint validates credentials and returns a token.\n\n"
        "## See also\n\n"
        "See [retry](../patterns/retry.md).\n",
        encoding="utf-8",
    )
    (root / "patterns" / "retry.md").write_text(
        "---\n"
        "title: Retry\n"
        "module: patterns\n"
        "---\n\n"
        "# Retry\n\n"
        "Use exponential backoff with full jitter to avoid retry storms.\n",
        encoding="utf-8",
    )


@pytest.fixture
def isolated_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate ``load_config()`` from the developer's real ``~/.lorewiki``.

    ``lorewiki.config.USER_CONFIG_PATH`` and
    ``lorewiki.utils.topic_shared.read_current_topic`` are module-level
    constants evaluated at *import* time, so ``monkeypatch.setenv("HOME")``
    alone cannot redirect them — we patch the symbols directly so
    ``load_config()`` sees only the temp dir.

    This matters because the developer's machine typically has a real
    ``~/.lorewiki/current`` pointing at a populated topic (e.g.
    ``wechat-miniprogram-api``); without this patch every ``call_tool``
    invocation would silently search that topic instead of the test wiki.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    # Point USER_CONFIG_PATH at a non-existent file under tmp_path so
    # ``user_cfg`` comes back empty; the project-level config.toml written
    # by the ``indexed_wiki`` fixture is what ``load_config()`` uses.
    monkeypatch.setattr(
        _config_module, "USER_CONFIG_PATH", tmp_path / ".lorewiki" / "config.toml"
    )
    # Force ``effective_topic = None`` so load_config() skips the topic
    # branch entirely (no topic config, no topic-derived project_dir).
    monkeypatch.setattr(_topic_shared, "read_current_topic", lambda: None)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def indexed_wiki(isolated_dir: Path) -> Path:
    """Seed a wiki, write its config.toml, and build the index.

    Depends on ``isolated_dir`` so ``load_config()`` (called inside
    ``call_tool``) resolves to this temp index, not the developer's
    real vault.
    """
    tmp_path = isolated_dir
    wiki = tmp_path / "wiki"
    _seed_wiki(wiki)

    config_dir = tmp_path / ".lorewiki"
    config_dir.mkdir(parents=True)
    cfg = LoreWikiConfig(wiki_path=wiki, db_path=config_dir / "index.db")
    save_config(cfg, config_dir / "config.toml")

    build_index(cfg, rebuild=True)
    return tmp_path


# ---------------------------------------------------------------------------
# list_tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tools_returns_three_tools() -> None:
    """The MCP server must advertise exactly search / show / tree."""
    tools = await list_tools()
    names = {t.name for t in tools}
    assert names == {"search", "show", "tree"}


@pytest.mark.asyncio
async def test_list_tools_have_input_schemas() -> None:
    """Each tool must carry a JSON Schema so the client can validate args."""
    tools = await list_tools()
    for tool in tools:
        assert tool.inputSchema["type"] == "object"
        assert "properties" in tool.inputSchema


# ---------------------------------------------------------------------------
# call_tool — search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_tool_search_returns_doc_summaries(indexed_wiki: Path) -> None:
    """search returns one entry per doc with a non-empty summary."""
    result = await call_tool("search", {"query": "auth login token", "top_k": 5})
    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert isinstance(payload, list)
    assert len(payload) >= 1

    auth_entry = next(
        (e for e in payload if e["doc_path"] == "api/auth.md"),
        None,
    )
    assert auth_entry is not None, f"api/auth.md missing from results: {payload}"
    assert auth_entry["title"] == "Auth"
    assert "summary" in auth_entry
    assert auth_entry["summary"], "summary must not be empty"


# ---------------------------------------------------------------------------
# call_tool — show
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_tool_show_returns_full_doc_and_related(
    indexed_wiki: Path,
) -> None:
    """show returns the full cleaned content + related_docs from edges."""
    result = await call_tool("show", {"doc_path": "api/auth.md"})
    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert payload["doc_path"] == "api/auth.md"
    assert payload["title"] == "Auth"
    assert "login endpoint" in payload["content"]
    # The auth.md body links to ../patterns/retry.md → captured as an edge.
    related_paths = [r["doc_path"] for r in payload["related_docs"]]
    assert "patterns/retry.md" in related_paths


@pytest.mark.asyncio
async def test_call_tool_show_missing_doc_returns_not_found(
    indexed_wiki: Path,
) -> None:
    """show on an unknown doc_path surfaces a clear not-found message."""
    result = await call_tool("show", {"doc_path": "does/not/exist.md"})
    assert len(result) == 1
    assert "not found" in result[0].text.lower()


# ---------------------------------------------------------------------------
# call_tool — tree
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_tool_tree_returns_node_list(indexed_wiki: Path) -> None:
    """tree returns the full hierarchy with root / module / doc nodes."""
    result = await call_tool("tree", {})
    assert len(result) == 1
    payload = json.loads(result[0].text)
    nodes = payload["nodes"]
    assert isinstance(nodes, list)
    assert len(nodes) > 0
    node_types = {n["node_type"] for n in nodes}
    assert {"root", "module", "doc"} <= node_types
    # Every non-root node carries a non-empty path so the client can
    # address it; the synthetic root's path is "" by design (indexer.py).
    non_root = [n for n in nodes if n["node_type"] != "root"]
    assert non_root, "expected at least one non-root node"
    assert all(n["path"] for n in non_root)


# ---------------------------------------------------------------------------
# call_tool — no index
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_tool_returns_hint_when_no_index(
    isolated_dir: Path,
) -> None:
    """When the index db is missing, the tool surfaces an actionable hint
    instead of raising — so the LLM client can guide the user to run
    ``lorewiki index`` first.
    """
    result = await call_tool("search", {"query": "anything"})
    assert len(result) == 1
    assert "No index found" in result[0].text


@pytest.mark.asyncio
async def test_call_tool_unknown_tool_returns_error(indexed_wiki: Path) -> None:
    """An unknown tool name surfaces a clear error rather than crashing."""
    result = await call_tool("nonexistent", {})
    assert len(result) == 1
    assert "Unknown tool" in result[0].text
