# LoreWiki agent skill — multi-tool installer

This directory ships a single, portable `SKILL.md` plus a cross-platform
installer that places it into every major AI coding tool that supports
the open [Agent Skills](https://agentskills.io) standard.

## What's in this folder

```
skills/
├── install.py             # ← single entry point (cross-platform Python)
├── install.ps1            # thin wrapper: forwards to install.py
├── install.sh             # thin wrapper: forwards to install.py
├── README.md              # this file
└── lorewiki/
    └── SKILL.md           # the skill definition (same for all tools)
```

The skill is identical for every tool — the `name` and `description`
frontmatter fields are universal, and tool-specific extensions (Claude's
`disable-model-invocation`, Cursor's `paths`) are silently ignored by
other tools, not rejected.

## Supported tools

| Tool              | User-level skills dir                              | Alias path also read     |
|-------------------|----------------------------------------------------|--------------------------|
| opencode          | `$XDG_CONFIG_HOME/opencode/skills/<name>`          | —                        |
| Claude Code       | `~/.claude/skills/<name>`                          | —                        |
| Codex CLI         | `$CODEX_HOME/skills/<name>`                        | —                        |
| Cursor            | `~/.cursor/skills/<name>`                          | `~/.agents/skills/<name>` |
| Gemini CLI        | `$GEMINI_HOME/skills/<name>`                       | `~/.agents/skills/<name>` |
| Google Antigravity| `~/.gemini/antigravity/skills/<name>`              | —                        |

For tools with an alias path (Cursor, Gemini) the installer also creates
a symlink at the alias so the skill is registered in both name spaces
with a single source of truth.

### Dedup: install Cursor after Gemini = no-op

Both Cursor and Gemini auto-discover `~/.agents/skills/<name>/`, so when
the user installs lorewiki for one of them, the *other* is also covered
via the shared alias. The installer detects this and skips a second
install rather than fighting over the alias:

```
$ python skills/install.py --tool cursor
source: /.../skills/lorewiki
mode:   copy

[Cursor]
  [dedup] Cursor served by existing alias /home/me/.agents/skills/lorewiki
          (shared ~/.agents/skills/ interop path); no action needed.
```

`--status` shows the relationship explicitly:

```
  [x] Cursor             /home/me/.cursor/skills/lorewiki
                                                         (via alias /home/me/.agents/skills/lorewiki)
  [x]   alias           /home/me/.agents/skills/lorewiki
  [x] Gemini CLI         /home/me/.gemini/skills/lorewiki
  [x]   alias           /home/me/.agents/skills/lorewiki
```

On uninstall, the alias is **reference-counted**: if the alias is still
serving another tool whose primary is installed, the alias is kept and
the uninstall reports `[alias-keep]`. Use `--force` to take it over.

## Prerequisites

The `lorewiki` CLI must be on your PATH. One-time install:

```powershell
uv tool install --editable . `
    --with fastapi --with "uvicorn[standard]" --with mcp
```

Verify:

```powershell
lorewiki --version    # expect: LoreWiki 0.1.0
```

## Install the skill

### One command for everything (recommended)

```bash
python skills/install.py --all            # install into every detected tool
python skills/install.py --all --symlink  # dev: live edits visible immediately
```

`--all` is a convenience: the script auto-detects which tools you have
(by looking for their config directory) and installs into those.

### Pick a subset

```bash
python skills/install.py --tool opencode,claude
python skills/install.py --tool cursor --symlink
```

If you pass no flags at all, the script lists what it detected and
prompts you to pick.

### Check current state

```bash
python skills/install.py --status
```

Prints which tools have the skill installed and whether each is a copy
or a symlink.

### Uninstall

```bash
python skills/install.py --uninstall --tool claude
python skills/install.py --uninstall --all
```

Removes the primary install path *and* any alias symlinks the installer
created.

### Other useful flags

| Flag        | Purpose                                                       |
|-------------|---------------------------------------------------------------|
| `--force`   | overwrite an existing install at the target path              |
| `--dry-run` | print what would happen without touching the disk             |
| `--tool`    | comma-separated tool ids; skip auto-detection                 |

## Why one skill file works for all tools

The Agent Skills standard defines a minimal `SKILL.md` shape:

```yaml
---
name: <skill-name>
description: <what it does + when to use it>
---
<markdown body>
```

Every tool on the table above reads that shape. Tool-specific
extensions (Claude's `disable-model-invocation`, Cursor's `paths`) are
additive — the file we ship doesn't use them, so every loader is happy.

The same logic the other way: a skill that uses Claude-only frontmatter
will *also* load in Cursor / Gemini, the extension fields will be
ignored. The standard is permissive on purpose.

## Windows symlink note

`--symlink` requires either:

- **Developer Mode** enabled in Windows Settings, **or**
- Running your terminal as Administrator

If neither is true, the installer falls back to a copy and tells you
why. For active development the copy is fine — just re-run after
editing the file. For a quick try, use copy mode (`--all` without
`--symlink`).

## Why this exists (vs. the bundled MCP server)

LoreWiki ships **both** an MCP stdio server (`lorewiki mcp`) **and** this
skill. They target different agents:

| Need                                            | Use           |
|-------------------------------------------------|---------------|
| Claude Desktop / Cursor (MCP-aware clients)     | MCP server    |
| opencode / Codex / Aider / any shell-using agent| This skill    |
| One-off shell scripting                         | The raw CLI   |

The skill route is lighter-weight: no JSON-RPC daemon to keep alive,
every call is one shell invocation, output is plain JSON when `--raw`
is used.

## Updating the skill

When the `lorewiki` CLI gains new commands or breaking changes, edit
`skills/lorewiki/SKILL.md` here, then re-run the install (use
`--symlink` during dev so live edits are visible without re-installing).

If you change the *installer* itself (this directory, not the skill),
no reinstall is needed — it's a one-shot tool the user runs manually.
