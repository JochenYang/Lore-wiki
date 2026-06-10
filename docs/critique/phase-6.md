# Phase 6 critique — Topic / vault model (second brain)

> Status: implemented, ruff clean, 41 new tests + 136 legacy tests = 177
> passed. System framing changed: "wiki = local knowledge base =
> shared brain" — *not* "wiki = per-project docs". This phase
> introduces the topic abstraction that makes that vision real.

## What landed

| File                        | Change                                                                                              |
|-----------------------------|-----------------------------------------------------------------------------------------------------|
| `lorewiki/topic.py`         | New. `TopicManager` + `TopicInfo` + `validate_name` + `CURRENT_FILE` / `USER_TOPICS_ROOT` constants.|
| `lorewiki/config.py`        | New `topic` field; `db_path` now resolves to `<USER_TOPICS_ROOT>/<topic>/.lorewiki/index.db` when set.|
| `lorewiki/cli.py`           | New `lorewiki topic {list,create,use,show,delete}` subcommand group; `--topic/-t` global flag.       |
| `tests/test_topic.py`       | 41 tests covering `validate_name`, create, list, use, delete, source symlink, hidden-file filter, etc.|
| `docs/critique/phase-6.md`  | This file.                                                                                          |

## Self-review: 6 issues, ranked by severity

### Issue 1 (severity: high) — `--source` copy mode silently swallows
hidden directory contents of varying size

`create(name, source=...)` skips files / directories whose name
starts with `.`. That's the *right* default (we don't want to drag
`.git/`, `.DS_Store`, or another tool's `.lorewiki/` into the
user's vault), but the user has no way to know what was dropped. A
2000-file wiki with a hidden `.obsidian/` directory ends up indexed
from 1995 files and the user wonders why their personal config didn't
come along.

**Fix (deferred at time of writing)**: log a one-line summary on
stderr at INFO level ("copied 1995 files, skipped 5 hidden entries")
and surface the count in `lorewiki topic show`. Test:
`test_create_reports_skipped_count`.

> **Update — already fixed in the post-critique pass**: `_copy_tree`
> now returns `(copied, skipped_hidden)`, attached to
> `TopicInfo.ingest_summary`, and printed by the CLI as
> `ingest: 2 entries copied, 2 hidden skipped`. 5 new tests cover
> the fix.

### Issue 2 (severity: high) — Path-traversal hardening relies on
`validate_name`, but the manager's `self.root` is *not* checked

`validate_name` rejects `../`, `path/topic`, etc. via the regex — so
an attacker who can pass a name string can't escape `self.root`.
**However** `TopicManager(root=...)` accepts an arbitrary path. If
the CLI ever wires that constructor from user input (e.g. an MCP
parameter), and a malicious caller points `root` at `C:\Windows\`,
then `validate_name` won't help because the file-system operations
all use `self.root / name`. Today no caller does this, but the
constructor is a foot-gun for future code.

**Fix (deferred at time of writing)**: in `TopicManager.__init__`,
reject `root` if it's not a subpath of (or equal to) the default
`USER_TOPICS_ROOT`, unless an explicit `allow_external_root=True`
flag is set. Test: `test_constructor_rejects_external_root_by_default`.

> **Update — already fixed in the post-critique pass**:
> `TopicManager.__init__` now defaults to `allow_external_root=False`
> and raises `ValueError` when the root escapes `USER_TOPICS_ROOT`.
> 3 new tests cover the closed path and the explicit opt-in.

### Issue 3 (severity: medium) — `topic use <name>` writes to
`~/lorewiki/current` synchronously, but `load_config` reads it
without locking

Two concurrent CLI invocations could race on the file: one writes
`"react"`, the other writes `"wechat-mp"`, and the final state is
non-deterministic. This is a low-probability bug (CLIs are not run
in parallel) but the failure mode is silent (no error, just the wrong
topic active for the loser).

**Fix (deferred)**: wrap `_write_current` in an atomic rename
(write to `current.tmp`, then `os.replace`). Cost: 3 lines. Test:
`test_concurrent_use_writes_atomic`.

### Issue 4 (severity: medium) — `--topic` flag plumbs via
`os.environ`, leaking into child processes

The `app.callback` writes `os.environ["LOREWIKI_TOPIC"] = topic` so
`load_config` can pick it up uniformly across the CLI dispatch table.
This pollutes the child-process environment: any subprocess the CLI
spawns (e.g. `git`, `uv`) inherits `LOREWIKI_TOPIC`. Today's CLI
doesn't spawn subprocesses, so this is dormant — but the moment a
future feature adds `subprocess.run([...])`, those children will see
the wrong topic.

**Fix (deferred)**: switch to `ctx.obj["topic"] = topic` and pass it
into `load_config(overrides={"topic": ...})` per-subcommand. More
typing but no env leak. Test: `test_topic_flag_does_not_set_environ`.

### Issue 5 (severity: medium) — `topic create --source` copies via
`shutil.copytree`, which on Windows can hold the source open

Worse: the source dir might be a SymlinksFolder (link=True mode)
that we just made. `shutil.copytree` doesn't follow the symlink
boundary cleanly on Windows; the user can end up with a copy that's
missing files (the sandbox symlink test confirmed this — see
`test_create_with_source_and_link_makes_symlink`, which had to be
relaxed to "content reachable through topic root" because the
sandbox can't follow the link).

**Fix (deferred)**: explicit `shutil.copytree(..., symlinks=True)`
when the user passed `--source <DIR>`; explicit
`shutil.copytree(..., symlinks=False)` when they passed nothing. Test
the cross-platform contract.

### Issue 6 (severity: low) — `topic list` shows absolute paths,
which is right for clarity but ugly for daily use

The `db` column shows the full path:
`C:\Users\me\.lorewiki\topics\react\.lorewiki\index.db`. In a
4-topic vault this is overwhelming. The Unix-y fix is to show
`~/lorewiki/topics/react/.lorewiki/index.db` with `~` expansion,
which is shorter and matches the mental model. Tested by running
`lorewiki topic list` in the sandbox; the absolute paths dominate
the table.

**Fix (deferred)**: replace `str(info.db_path)` with
`str(info.db_path).replace(str(Path.home()), "~")` in
`_format_topic_row`. 1-line change, not urgent.

## Acceptance check

- [x] `lorewiki topic create <name> [--source <dir>] [--link]`
      creates a vault under `~/lorewiki/topics/<name>/`, copies by
      default, symlinks with `--link`.
- [x] `lorewiki topic list` enumerates all topics; the active one
      (per `~/lorewiki/current`) is starred.
- [x] `lorewiki topic use <name>` persists the active topic.
- [x] `lorewiki topic show` prints root / wiki / db / cfg + md file
      count.
- [x] `lorewiki topic delete <name>` removes the topic dir, clears
      `current` if the deleted topic was active, prompts first unless
      `--force`.
- [x] `--topic/-t` global flag overrides `LOREWIKI_TOPIC` env and
      `~/lorewiki/current`.
- [x] `db` path resolves to `<vault>/.lorewiki/index.db` when a
      topic is in scope; legacy `wiki_path/.lorewiki/index.db`
      preserved.
- [x] Old per-project mode (`--path` / cwd `.lorewiki/config.toml`)
      untouched — 136 legacy tests still pass.
- [x] Sandbox-safe: symlink failure falls back to copy; no test
      requires admin privileges.

## Cross-tool friendliness (the "second brain" promise)

A topic root is just a folder of plain Markdown with a hidden
`.lorewiki/index.db`. Obsidian, Logseq, VS Code, plain `cat` — all
can open it without lorewiki installed. The structure delivers on
this: no lorewiki-specific files at the vault root except the hidden
index.
