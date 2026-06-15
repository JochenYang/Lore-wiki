"""Topic / vault management — the "second brain" abstraction.

A *topic* (a.k.a. *vault* in Obsidian terminology) is one isolated
knowledge domain that the user wants to index separately:

    ~/lorewiki/                       # central root (USER_CONFIG_DIR)
    ├── config.toml                   # global: LLM key, default_topic
    ├── current                       # text file: name of the active topic
    └── react/                        # one topic = one vault
        ├── .lorewiki/
        │   └── index.db              # lorewiki-only metadata, hidden
        ├── api/
        │   ├── auth.md
        │   └── user.md
        └── architecture.md

Why "topic" and not "vault": the CLI command is short. The model is
the same — one isolated knowledge domain, persisted in the user's
home, shareable across any project the user works in (their
"second brain"). Obsidian users will recognise the layout: the topic
root is also a valid Obsidian vault.

Design contract
---------------

* **Isolation** — each topic has its own index.db and its own source
  markdown. Searching for "JWT" in the ``react`` topic won't return
  results from the ``wechat-mp`` topic, even if both have a file
  that mentions JWT.
* **Cross-project** — topics live under the user's home, not under
  any project. Open any project, run ``lorewiki search "..."``,
  the active topic is queried. No setup per project.
* **Cross-tool** — the topic root is just a folder of plain
  Markdown with frontmatter. Open it in Obsidian, Logseq, VS Code,
  a plain text editor, anything. The only lorewiki-specific file is
  ``.lorewiki/index.db`` which is hidden by default and ignored by
  most tools.
* **Backwards compatible** — the old per-wiki / per-project mode
  (``--path <WIKI_DIR>``) still works. The topic system is a
  convenience, not a replacement.

The ``lorewiki topic`` subcommand is the user-facing entry point;
:class:`TopicManager` is the library API the CLI binds to.
"""
from __future__ import annotations

import contextlib
import re
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

from lorewiki.utils.logger import get_logger
from lorewiki.utils.topic_shared import (
    CURRENT_FILE,
    USER_CONFIG_DIR,
    USER_TOPICS_ROOT,
)
from lorewiki.utils.topic_shared import (
    read_current_topic as _read_current_topic_shared,
)

log = get_logger(__name__)

# Topic name rules: lowercase ASCII letters, digits, hyphens. No
# slashes, dots, spaces, or unicode so the name is always safe to
# splice into a path and a shell argument on every OS. Length 1-64.
# ``-`` is allowed but not as the first character (would look like
# a flag) — we strip a leading hyphen defensively but the regex
# forbids it.
_TOPIC_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")

# Reserved names that collide with CLI subcommands or shell semantics.
_RESERVED_NAMES = frozenset({
    "init", "index", "search", "ask", "status", "config", "rest",
    "ui", "mcp", "update", "topic", "current", "all", "help",
    "con", "prn", "aux", "nul",  # Windows reserved device names
})




class TopicNameError(ValueError):
    """Raised when a topic name violates the naming rules."""


@dataclass(frozen=True)
class TopicInfo:
    """Immutable snapshot of a single topic's state on disk.

    ``chunks`` and ``last_indexed`` are loaded lazily from the index
    DB the first time :meth:`TopicManager.inspect` is called; they
    are ``None`` for fresh topics that have never been indexed.
    """

    name: str
    root: Path
    wiki_path: Path
    db_path: Path
    config_path: Path
    chunks: int | None = None
    last_indexed: str | None = None
    source_link: bool = False  # True if wiki_path is a symlink (--link mode)
    # ``ingest_summary`` is a transient field populated by
    # ``TopicManager.create`` when ``--source`` is used; it's a tuple
    # ``(copied: int, skipped_hidden: int)`` so the CLI can show
    # "copied 1995 files, skipped 5 hidden". ``None`` for empty /
    # no-source topics. Not part of the on-disk identity — just
    # telemetry for the create path.
    ingest_summary: tuple[int, int] | None = None

    def exists(self) -> bool:
        """True if the topic root directory exists on disk."""
        return self.root.is_dir()


# ---------------------------------------------------------------------------
# Name validation
# ---------------------------------------------------------------------------


def validate_name(name: str) -> None:
    """Raise :class:`TopicNameError` if ``name`` is unsafe or reserved.

    Allowed: lowercase ASCII letters, digits, and hyphens. Length 1-64.
    Disallowed: leading/trailing hyphens, reserved CLI / OS names.
    """
    if not isinstance(name, str):
        raise TopicNameError(f"topic name must be a string, got {type(name).__name__}")
    if not name:
        raise TopicNameError("topic name must not be empty")
    if not _TOPIC_NAME_RE.match(name):
        raise TopicNameError(
            f"invalid topic name {name!r}: must match "
            f"^[a-z0-9][a-z0-9-]{{0,62}}[a-z0-9]$ "
            f"(lowercase, digits, hyphens; 1-64 chars; no leading/trailing hyphen)"
        )
    if name in _RESERVED_NAMES:
        raise TopicNameError(
            f"topic name {name!r} is reserved (CLI subcommand or OS device name); "
            f"pick something else"
        )


# ---------------------------------------------------------------------------
# Name suggestion
# ---------------------------------------------------------------------------

# Tiny English stop-word set. CJK descriptions return no suggestions
# — Chinese-only inputs require transliteration (pypinyin) which we
# deliberately avoid as a hard dependency. The CLI surfaces a friendly
# "no suggestions" message and tells the user to name the topic by hand.
_SUGGEST_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "to", "for", "in", "on",
    "with", "by", "from", "as", "at", "is", "it", "this", "that",
    "wiki", "vault", "notes", "note", "doc", "docs", "documentation",
    "learn", "learning", "guide", "tutorial", "intro", "introduction",
    "about",
})

# Common library / framework suffixes we keep because they're meaningful
# in a vault name ("react-hooks" is clearer than "reacthooks-hooks").
_SUGGEST_KEEP = frozenset({
    "js", "ts", "py", "rb", "go", "rs", "kt", "swift", "vue", "react",
    "angular", "svelte", "node", "deno", "bun", "rust", "java", "kotlin",
    "cocos", "unity", "unreal", "godot", "mp", "miniprogram", "wx",
    "llm", "ai", "ml", "dl", "rl", "nlp", "cv", "rlhf",
})

_MAX_SUGGESTIONS = 4
_MAX_NAME_LEN = 64


def _slug_tokenize(description: str) -> list[str]:
    """Turn ``"React Hooks Learning Notes"`` into ``["react", "hooks"]``.

    The pipeline is:
    1. Lowercase.
    2. Replace every non ``[a-z0-9]`` character with a space.
    3. Split on whitespace.
    4. Drop pure-stopwords, but keep short technical suffixes from
       ``_SUGGEST_KEEP`` even if they overlap.
    """
    text = description.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    raw_tokens = text.split()
    tokens: list[str] = []
    for t in raw_tokens:
        if t in _SUGGEST_KEEP:
            tokens.append(t)
        elif t in _SUGGEST_STOPWORDS:
            continue
        elif len(t) <= 2:
            # Single letters and 2-letter stop-ish tokens — drop.
            # (Multi-char tech terms are already in _SUGGEST_KEEP.)
            continue
        else:
            tokens.append(t)
    return tokens


def suggest_names(  # branched for collision-avoidance + token variants
    description: str, existing: list[str] | None = None, *,
    limit: int = _MAX_SUGGESTIONS,
) -> list[str]:
    """Return up to ``limit`` candidate topic names for ``description``.

    The algorithm is intentionally simple and rule-based — no LLM,
    no network. We:

    1. Slugify the description (drop stopwords, keep tech terms).
    2. Emit 1, 2, and 3-token candidates (longer first; in
       source-order for ties).
    3. Validate each candidate against :func:`validate_name`.
    4. If a candidate collides with an existing topic, append
       ``-2``, ``-3``, etc., until the suffixed name is free.

    Limitations:
    * CJK / non-ASCII descriptions return ``[]`` (the slugifier can't
      transliterate). The CLI surfaces this and tells the user to
      name the topic by hand.
    * Suggestions are deterministic and short — they're a starting
      point, not the final answer. Always show the user the options.

    Parameters
    ----------
    description
        Free-form text like ``"react hooks learning"``.
    existing
        Topic names that already exist on disk. Used to suffix
        duplicates (``react-2``). Defaults to ``[]`` (callers in the
        CLI pass ``TopicManager().list()``).
    limit
        Maximum number of suggestions to return.
    """
    existing_set = set(existing or [])
    tokens = _slug_tokenize(description)
    if not tokens:
        return []

    raw_candidates: list[str] = []
    # Single-token is always emitted.
    raw_candidates.append(tokens[0])
    # Adjacent pairs, in source order. We try every adjacent pair so
    # "react hooks notes" yields ["react-hooks", "hooks-notes"] not
    # just the first.
    for i in range(len(tokens) - 1):
        joined = f"{tokens[i]}-{tokens[i + 1]}"
        if joined not in raw_candidates:
            raw_candidates.append(joined)
    # Triplet if available.
    if len(tokens) >= 3:
        joined3 = "-".join(tokens[:3])
        if joined3 not in raw_candidates:
            raw_candidates.append(joined3)

    seen: set[str] = set()
    result: list[str] = []
    for cand in raw_candidates:
        if len(cand) > _MAX_NAME_LEN:
            continue
        try:
            validate_name(cand)
        except TopicNameError:
            continue
        if cand in seen:
            # Earlier entry covered this candidate; don't double-emit.
            continue
        if cand in existing_set:
            # Need to find a free suffixed name (-2, -3, ...).
            final: str | None = None
            i = 2
            while True:
                suffixed = f"{cand}-{i}"
                if len(suffixed) > _MAX_NAME_LEN:
                    break
                if suffixed in seen or suffixed in existing_set:
                    i += 1
                    continue
                final = suffixed
                break
            if final is None:
                # No free suffix under the length cap; skip.
                continue
            seen.add(final)
            result.append(final)
        else:
            # Cand is free; emit as-is.
            seen.add(cand)
            result.append(cand)
        if len(result) >= limit:
            break
    return result


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class TopicManager:
    """CRUD-style API for the user's topic collection.

    The manager is stateless apart from the root path; every call
    hits the disk. That's fine because all operations are
    user-initiated (a CLI invocation) — we don't expect hot-path
    traffic.
    """

    def __init__(
        self,
        root: Path | None = None,
        *,
        allow_external_root: bool = False,
    ) -> None:
        """Construct a manager.

        Parameters
        ----------
        root
            The directory under which topics live. Defaults to
            :data:`USER_TOPICS_ROOT` (``~/.lorewiki/topics``).
        allow_external_root
            If ``True``, accept any ``root`` value, even outside the
            user's home. The CLI never sets this; it's a hatch for
            tests, the install script, and any future cross-user
            tooling (e.g. an admin tool that manages a service-wide
            topic directory). Defaults to ``False`` so a caller
            passing an arbitrary path (e.g. driven by a config
            file that came from untrusted input) cannot accidentally
            install into a directory that escapes the user's home —
            :class:`ValueError` is raised instead.
        """
        target = (root or USER_TOPICS_ROOT).resolve()
        if not allow_external_root:
            default_root = USER_TOPICS_ROOT.resolve()
            # We allow either the default itself, or any directory
            # underneath it (e.g. for future "sub-namespace" managers
            # like a team-shared branch). ``target in default_root.parents``
            # walks up from target and returns True if it ever hits
            # default_root.
            if target != default_root and default_root not in target.parents:
                raise ValueError(
                    f"TopicManager root {target!s} escapes the default "
                    f"USER_TOPICS_ROOT ({default_root}); pass "
                    f"allow_external_root=True to use a custom location"
                )
        self.root = target

    # -- queries ----------------------------------------------------------

    def exists(self, name: str) -> bool:
        validate_name(name)
        return (self.root / name).is_dir()

    def get(self, name: str) -> TopicInfo:
        """Return the :class:`TopicInfo` for ``name``; raise if missing."""
        validate_name(name)
        topic_root = self.root / name
        if not topic_root.is_dir():
            raise FileNotFoundError(f"topic {name!r} not found at {topic_root}")
        return self._info_for(name, topic_root)

    def list(self) -> list[TopicInfo]:
        """Return every topic on disk, sorted by name, with the active
        one first if any. Topics whose root is malformed (no readable
        subdirs) are silently skipped — they are the user's
        unrelated ``~/.lorewiki/topics/`` content, not lorewiki topics.
        """
        if not self.root.is_dir():
            return []
        current = self._read_current()
        infos: list[TopicInfo] = []
        for child in sorted(self.root.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            if not _TOPIC_NAME_RE.match(child.name):
                # Looks like the user put something else here. Skip.
                continue
            if child.name in _RESERVED_NAMES:
                continue
            try:
                infos.append(self._info_for(child.name, child))
            except (OSError, ValueError) as exc:
                log.warning("skipping malformed topic {}: {}", child, exc)
                continue
        # Active topic first, then alphabetical.
        infos.sort(key=lambda i: (i.name != current, i.name))
        return infos

    def current(self) -> str | None:
        """Return the name of the active topic, or ``None`` if unset."""
        return self._read_current()

    def resolve_active(self) -> TopicInfo | None:
        """Return the active topic's info, or ``None`` if not set."""
        name = self.current()
        if name is None:
            return None
        try:
            return self.get(name)
        except FileNotFoundError:
            log.warning(
                "current topic {name!r} not found on disk; clearing pointer", name=name,
            )
            self._write_current(None)
            return None

    # -- mutations --------------------------------------------------------

    def create(
        self,
        name: str,
        *,
        source: Path | None = None,
        link: bool = False,
    ) -> TopicInfo:
        """Create a new topic.

        The return value is a :class:`TopicInfo`; the secondary
        ``ingest_summary`` attribute (set after construction) holds a
        tuple ``(copied, skipped_hidden)`` when ``--source`` was used.
        Callers (the CLI) read it to tell the user how many hidden
        entries were filtered out.

        Parameters
        ----------
        name : str
            Validated against :func:`validate_name`.
        source : Path, optional
            If given, the topic's wiki dir is populated from this
            source directory. Default mode (``link=False``) **copies**
            ``source/<files>`` into the new vault so the user owns
            the data outright. ``link=True`` **symlinks** the source
            instead — the wiki files stay in place, the topic is
            just a way to index them. Use ``--link`` for throwaway
            exploration; use copy mode (default) for durable vaults.
        link : bool
            See ``source``. Has no effect when ``source`` is None.

        Raises
        ------
        TopicNameError
            If ``name`` is invalid.
        FileExistsError
            If a topic with this name already exists.
        FileNotFoundError
            If ``source`` is given but does not exist.
        """
        validate_name(name)
        self.root.mkdir(parents=True, exist_ok=True)
        topic_root = self.root / name
        if topic_root.exists():
            raise FileExistsError(f"topic {name!r} already exists at {topic_root}")
        topic_root.mkdir(parents=False, exist_ok=False)
        # Ensure .lorewiki exists for the index; create the wiki dir
        # at the *vault root* (no wiki/ subdirectory — PKM-friendly).
        (topic_root / ".lorewiki").mkdir(exist_ok=True)
        source_link = False
        # Ingest summary default; only set when ``--source`` actually
        # triggers a copy. Symlink success path leaves this at the
        # default because no bytes were copied.
        ingest: tuple[int, int] = (0, 0)
        if source is not None:
            source_path = source.expanduser().resolve()
            if not source_path.is_dir():
                # Clean up the half-built topic dir in reverse order
                # (.lorewiki was created first, then its parent).
                (topic_root / ".lorewiki").rmdir()
                topic_root.rmdir()
                raise FileNotFoundError(
                    f"source wiki path {source_path} does not exist or is not a directory"
                )
            if link:
                # Symlink: replace ``topic_root`` (which already has
                # a ``.lorewiki/`` subdir) with a symlink to the
                # source, then move the .lorewiki back inside the
                # symlinked path. The stash lives next to the topic
                # root so the move is a fast rename.
                # Ingest summary placeholder — set to (0, 0) on the
                # pure-symlink success path because we don't actually
                # copy any content; populated on the fallback path.
                stash = self.root / f".lorewiki-stash-{name}"
                shutil.move(topic_root / ".lorewiki", stash)
                topic_root.rmdir()
                try:
                    topic_root.symlink_to(source_path, target_is_directory=True)
                except OSError:
                    # Sandbox / non-admin token: fall back to copy so
                    # the user isn't blocked.
                    log.warning(
                        "symlink failed for topic {name!r}; falling back to copy",
                        name=name,
                    )
                    topic_root.mkdir()
                    shutil.move(stash, topic_root / ".lorewiki")
                    ingest = self._copy_tree(source_path, topic_root)
                else:
                    shutil.move(stash, topic_root / ".lorewiki")
                    source_link = True
            else:
                # Copy mode (default): bring the source content in.
                ingest = self._copy_tree(source_path, topic_root)
        # NOTE: we deliberately do NOT seed a per-topic ``config.toml``.
        # LoreWiki config lives in **one** place: ``~/.lorewiki/config.toml``.
        # Dropping a TOML into every topic root polluted the vault view
        # in Obsidian / Logseq and gave users a false impression that
        # vault-local overrides were the norm. Per-topic overrides are
        # still possible (by editing the global file with the topic name
        # as a section header) but the default is single-source.
        log.info("created topic {name!r} at {root}", name=name, root=topic_root)
        info = self._info_for(name, topic_root, source_link=source_link)
        # Attach the ingest summary as a transient attribute so the
        # CLI can surface "copied N files, skipped M hidden entries"
        # without having to re-stat the tree. ``None`` when no source
        # was used (no copy happened). ``TopicInfo`` is frozen, so
        # we use ``dataclasses.replace`` to build a new instance.
        if source is not None:
            info = replace(info, ingest_summary=ingest)
        return info

    def rename(self, old: str, new: str) -> TopicInfo:
        """Rename a topic in place.

        Behaviour:
        - Validates the new name against the same rules as :func:`validate_name`.
        - Rejects renaming to a name that already exists.
        - Updates ``~/lorewiki/current`` if the renamed topic was the
          active one, so a subsequent ``lorewiki search`` keeps working
          without re-running ``topic use``.

        The on-disk database, the seeded config, the wiki source — all
        move with the directory; nothing inside is touched. The rename
        is a single ``Path.rename`` call (atomic on the same
        filesystem, which is always the case for ``~/lorewiki/topics/``).
        """
        validate_name(new)
        old_root = self.root / old
        new_root = self.root / new
        if not old_root.is_dir():
            raise FileNotFoundError(f"topic {old!r} not found at {old_root}")
        if new_root.exists() and new_root.resolve() != old_root.resolve():
            raise FileExistsError(
                f"target {new!r} already exists at {new_root}; "
                f"delete it first or pick a different name"
            )
        if old == new:
            return self._info_for(new, old_root)
        was_active = self.current() == old
        old_root.rename(new_root)
        if was_active:
            self._write_current(new)
        log.info("renamed topic {old!r} -> {new!r}", old=old, new=new)
        return self._info_for(new, new_root)

    def delete(self, name: str, *, force: bool = False) -> None:
        """Hard-delete a topic's directory.

        ``force=False`` requires :meth:`confirm` to be called first
        by the caller (the CLI does the y/N prompt); this method
        just deletes. We do **not** soft-delete / trash by default
        per the design decision (2026-06).

        If the deleted topic is the active one, the ``current``
        pointer is cleared so the user isn't left with a dangling
        reference.
        """
        validate_name(name)
        topic_root = self.root / name
        if not topic_root.is_dir():
            raise FileNotFoundError(f"topic {name!r} not found at {topic_root}")
        shutil.rmtree(topic_root)
        log.info("deleted topic {name!r} at {root}", name=name, root=topic_root)
        if self.current() == name:
            self._write_current(None)

    def use(self, name: str) -> TopicInfo:
        """Mark ``name`` as the active topic (write ``~/lorewiki/current``)."""
        info = self.get(name)  # raises FileNotFoundError if missing
        self._write_current(name)
        log.info("switched active topic to {name!r}", name=name)
        return info

    # -- helpers ----------------------------------------------------------

    def _info_for(
        self, name: str, topic_root: Path, *, source_link: bool = False,
    ) -> TopicInfo:
        """Build a :class:`TopicInfo` for a topic directory.

        If the topic's wiki dir is a symlink, ``source_link`` is set
        on the returned info so callers can render a ``(linked)``
        badge in ``lorewiki topic list``.
        """
        wiki_path = topic_root
        db_path = topic_root / ".lorewiki" / "index.db"
        config_path = topic_root / "config.toml"
        link = source_link or (wiki_path.is_symlink())
        return TopicInfo(
            name=name,
            root=topic_root.resolve(),
            wiki_path=wiki_path.resolve(),
            db_path=db_path.resolve(),
            config_path=config_path.resolve(),
            source_link=link,
        )

    @staticmethod
    def _read_current() -> str | None:
        return _read_current_topic_shared()

    @staticmethod
    def _write_current(name: str | None) -> None:
        CURRENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        if name is None:
            with contextlib.suppress(FileNotFoundError):
                CURRENT_FILE.unlink()
            return
        CURRENT_FILE.write_text(name + "\n", encoding="utf-8")

    @staticmethod
    def _copy_tree(src: Path, dst: Path) -> tuple[int, int]:
        """Copy markdown content from ``src`` into ``dst``.

        Skips hidden directories and files (``.lorewiki``, ``.git``,
        ``.DS_Store``, etc.) so the user doesn't accidentally copy
        another tool's metadata into their vault. Files at the top
        level are copied verbatim.

        Returns ``(copied, skipped_hidden)`` — top-level *entries*
        (a file counts as 1, a directory counts as 1 regardless of
        how many files it contains). The caller surfaces the
        skipped count to the user.
        """
        copied = 0
        skipped = 0
        for child in src.iterdir():
            if child.name.startswith("."):
                skipped += 1
                continue
            target = dst / child.name
            if child.is_dir():
                shutil.copytree(child, target)
            else:
                shutil.copy2(child, target)
            copied += 1
        return copied, skipped

    @staticmethod
    def _seed_config(topic_root: Path) -> None:
        """Deprecated: kept as a no-op so older callers don't break.

        LoreWiki config now lives in **one** place:
        ``~/.lorewiki/config.toml``. We don't drop a ``config.toml``
        into the topic root any more (it polluted the vault view in
        Obsidian / Logseq and gave users a false impression that
        per-topic overrides were the default).

        If you want per-topic overrides, the supported path is to
        edit ``~/.lorewiki/config.toml`` with a ``[topics.<name>]``
        section header. See ``docs/how-it-works.md`` for the
        resolution priority.
        """
        return


__all__ = [
    "CURRENT_FILE",
    "USER_CONFIG_DIR",
    "USER_TOPICS_ROOT",
    "TopicInfo",
    "TopicManager",
    "TopicNameError",
    "validate_name",
]
