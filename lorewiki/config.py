"""LoreWiki configuration loader.

Sources are merged in this order (later overrides earlier):

1. Pydantic field defaults.
2. User-level TOML  (``~/.lorewiki/config.toml``).
3. Topic-level TOML (``~/.lorewiki/topics/<active>/config.toml``), only
   when a topic is in scope. See :mod:`lorewiki.topic`.
4. Project-level TOML (``<cwd or project_dir>/.lorewiki/config.toml``).
5. Environment variables (prefixed ``LOREWIKI_``; nested via double underscore).
6. Explicit ``overrides`` argument passed to :func:`load_config`.

The merged result is validated against :class:`LoreWikiConfig` (a
``pydantic_settings.BaseSettings`` subclass) so every key has a type and a
default; unknown keys raise a clear error instead of being silently dropped.

Topic resolution (which topic's config to load) follows this priority:

1. ``topic`` field on the config (set via ``--topic`` flag, ``LOREWIKI_TOPIC``
   env var, or explicit ``overrides``).
2. ``~/lorewiki/current`` text file (the user's last-used topic).
3. ``None`` — falls back to the legacy per-wiki / per-project mode where
   ``wiki_path`` and ``db_path`` are project-local.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - py3.10 fallback
    import tomli as tomllib

import tomli_w

from lorewiki.utils.logger import get_logger

log = get_logger(__name__)

USER_CONFIG_DIR = Path.home() / ".lorewiki"
USER_CONFIG_PATH = USER_CONFIG_DIR / "config.toml"
PROJECT_CONFIG_REL = Path(".lorewiki") / "config.toml"


def _read_current_topic_file() -> str | None:
    """Return the name of the active topic per ``~/lorewiki/current``,
    or ``None`` if the file is missing / empty. Duplicated from
    :mod:`lorewiki.topic` to avoid a circular import (config is
    imported by topic callers indirectly via cli).
    """
    path = USER_CONFIG_DIR / "current"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


class MixWeights(BaseModel):
    """Per-retriever weights used by the RRF fusion (phase 2)."""

    bm25: float = 1.0
    hierarchy: float = 0.8
    vector: float = 0.5


class LLMConfig(BaseModel):
    enabled: bool = False
    backend: Literal["ollama", "openai"] = "ollama"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = "gpt-4o-mini"
    timeout_seconds: float = 30.0


class VectorConfig(BaseModel):
    enabled: bool = False
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384


class LoreWikiConfig(BaseSettings):
    """Top-level LoreWiki configuration object."""

    model_config = SettingsConfigDict(
        env_prefix="LOREWIKI_",
        env_nested_delimiter="__",
        extra="forbid",
        case_sensitive=False,
    )

    wiki_path: Path = Field(default_factory=lambda: Path("./wiki"))
    db_path: Path | None = None
    topic: str | None = None
    retrieval_mode: Literal["mix", "bm25", "hierarchy", "vector"] = "mix"
    mix_weights: MixWeights = Field(default_factory=MixWeights)
    rrf_k: int = 60
    chunk_max_tokens: int = 800
    chunk_overlap_tokens: int = 100
    chunk_min_chars: int = 40
    snippet_chars: int = 240
    llm: LLMConfig = Field(default_factory=LLMConfig)
    vector: VectorConfig = Field(default_factory=VectorConfig)

    @model_validator(mode="after")
    def _resolve_paths(self) -> LoreWikiConfig:
        """Expand ``~`` and make wiki_path / db_path absolute.

        Resolution rules (db_path is the branchy one):
        - ``db_path`` explicitly set → use it.
        - ``topic`` set → ``<USER_TOPICS_ROOT>/<topic>/.lorewiki/index.db``.
        - Neither → legacy per-wiki path: ``<wiki_path>/.lorewiki/index.db``.
        """
        self.wiki_path = Path(self.wiki_path).expanduser().resolve()
        if self.db_path is not None:
            self.db_path = Path(self.db_path).expanduser().resolve()
            return self
        if self.topic:
            from lorewiki.topic import USER_TOPICS_ROOT, validate_name  # noqa: PLC0415
            validate_name(self.topic)
            self.db_path = (USER_TOPICS_ROOT / self.topic / ".lorewiki" / "index.db").resolve()
            return self
        self.db_path = (self.wiki_path / ".lorewiki" / "index.db").resolve()
        return self


def _load_toml(path: Path) -> dict[str, Any]:
    """Return the parsed TOML at ``path`` or ``{}`` if it doesn't exist."""
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        msg = f"failed to parse TOML at {path}: {exc}"
        raise RuntimeError(msg) from exc


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into ``base`` returning a new dict."""
    out: dict[str, Any] = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(
    *,
    project_dir: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> LoreWikiConfig:
    """Load config from disk + env + overrides (later wins).

    Layered merge order:
        global (~/.lorewiki/config.toml)
        → topic (~/.lorewiki/topics/<active>/config.toml, only if active topic)
        → project (<project_dir>/.lorewiki/config.toml)
        → overrides
    """
    user_cfg = _load_toml(USER_CONFIG_PATH)

    # Resolve the active topic. The CLI normally injects the
    # ``topic`` key into ``overrides``; here we also honour the
    # ``~/lorewiki/current`` file so env-less calls (e.g. the
    # Streamlit UI) still see the right topic.
    from lorewiki.topic import USER_TOPICS_ROOT  # noqa: PLC0415
    effective_topic: str | None = None
    if overrides and "topic" in overrides and overrides["topic"]:
        effective_topic = overrides["topic"]
    if not effective_topic:
        effective_topic = _read_current_topic_file()

    topic_cfg: dict[str, Any] = {}
    if effective_topic:
        topic_path = USER_TOPICS_ROOT / effective_topic / "config.toml"
        topic_cfg = _load_toml(topic_path)

    project_dir = (project_dir or Path.cwd()).resolve()
    project_cfg = _load_toml(project_dir / PROJECT_CONFIG_REL)

    merged = _deep_merge(user_cfg, topic_cfg)
    merged = _deep_merge(merged, project_cfg)
    if overrides:
        merged = _deep_merge(merged, overrides)
    try:
        cfg = LoreWikiConfig(**merged)
    except ValidationError as exc:
        msg = f"invalid configuration: {exc}"
        raise RuntimeError(msg) from exc
    log.debug(
        "loaded config: user={} topic={} project={} overrides={}",
        USER_CONFIG_PATH if user_cfg else None,
        effective_topic,
        (project_dir / PROJECT_CONFIG_REL) if project_cfg else None,
        list(overrides or {}),
    )
    return cfg


def save_config(cfg: LoreWikiConfig, target: Path) -> None:
    """Serialize ``cfg`` to ``target`` as TOML, creating parent dirs.

    ``None`` values are dropped (via ``exclude_none=True``) because
    ``tomli_w`` cannot serialise them and the only fields that
    default to ``None`` (``db_path``, ``topic``) are always
    resolved before they reach disk.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    data = cfg.model_dump(mode="json", exclude_none=True)
    # Convert PosixPath / WindowsPath to string for TOML serialization.
    data = _stringify_paths(data)
    target.write_text(tomli_w.dumps(data), encoding="utf-8")


def _stringify_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _stringify_paths(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_stringify_paths(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def default_config_toml() -> str:
    """Return a default config.toml content as a string (used by ``lorewiki init``)."""
    cfg = LoreWikiConfig()
    data = _stringify_paths(cfg.model_dump(mode="json", exclude_none=True))
    return tomli_w.dumps(data)


__all__ = [
    "PROJECT_CONFIG_REL",
    "USER_CONFIG_PATH",
    "LLMConfig",
    "LoreWikiConfig",
    "MixWeights",
    "VectorConfig",
    "default_config_toml",
    "load_config",
    "save_config",
]
