# LoreWiki — new-session smoke test

> What to type into a **fresh** opencode session to confirm the
> `lorewiki` skill is wired up end-to-end. Run after every install
> or SKILL.md update; takes 5 minutes.

## 0. Pre-flight (30 s)

```powershell
# confirm the wheel-install + user-level skill are in sync
lorewiki --version                # expect: LoreWiki 0.1.0
Test-Path "C:\Users\Administrator\.config\opencode\skills\lorewiki\SKILL.md"
                              # expect: True
```

If `lorewiki` is not on PATH:

```powershell
uv tool install --editable "D:\codes\Lorewiki" --with fastapi --with "uvicorn[standard]" --with mcp
```

## 1. Cold-cache trigger (English)

In a **fresh** opencode session, type literally:

```
look up "how does our retry policy work" in the wiki
```

**Expected agent behaviour**:
1. The agent invokes the `lorewiki` skill automatically (trigger word: `wiki`).
2. The agent shells out: `lorewiki search "how does our retry policy work" --raw --mode mix --top-k 5`.
3. The agent receives a JSON array of hits, picks the top 1-3, and answers **with `doc_path` citations** like `[patterns/retry.md]`.
4. The agent does **not** re-explain the chunks verbatim — it summarises and cites.

## 2. Cold-cache trigger (Chinese)

In the same session, type:

```
帮我查一下 wiki 里关于"令牌桶限流"的内容
```

**Expected agent behaviour**:
1. Skill triggered (Chinese trigger: `wiki`, `查`).
2. Agent runs `lorewiki search "令牌桶限流" --raw --mode mix --top-k 5`.
3. CJK-friendly retrieval returns a hit in `patterns/rate-limit.md`.
4. Agent answers in Chinese, with `[patterns/rate-limit.md]` citation.

## 3. Path-handling probe (no `--path`)

```
search "JWT" with the active topic
```

**Expected**:
- Agent reads `~/lorewiki/current` (or asks you via the priority
  chain in `SKILL.md` §Path Handling Convention).
- If you have a topic active: agent uses it.
- If you don't: agent uses `--path` against a `cwd` `.lorewiki/config.toml`
  if one exists, or runs a bounded-depth scan to find one.

## 4. Write-back probe (decision persistence)

```
save this to the wiki: "We decided to use Redis Streams for the event bus
instead of Kafka. Reason: lower ops burden for our team size."
```

**Expected**:
- Agent creates `<wiki>/decisions/redis-streams.md` with the
  right frontmatter (`title` / `module` / `tags` / `owner`).
- Agent runs `lorewiki index --path <wiki>` (incremental).
- Agent re-searches "Redis Streams decision" to confirm it's now findable.

## 5. Failure-mode probe (graceful degradation)

```
search "asdfgh-no-such-term" with the active topic
```

**Expected**:
- Either the search returns `[]` and the agent says plainly
  "no results in the wiki" — **or** — the agent suggests a
  related term (e.g. it falls back to `--mode bm25` to inspect
  scores).
- The agent does **not** hallucinate content that isn't in the wiki.

## 6. Optional: REST API smoke

```
lorewiki rest --port 8000
```

…in a separate terminal (the agent doesn't run blocking servers).
Note: lorewiki no longer ships a built-in web UI in 0.1.0.
Open <http://127.0.0.1:8501>, click around the 4 pages
(Search / Browse / Config / Status).

## What to watch for

If anything goes wrong, the most common failure modes are:

| Symptom                                           | Cause                                              | Fix                                                                                              |
|---------------------------------------------------|----------------------------------------------------|--------------------------------------------------------------------------------------------------|
| Agent says "I don't have access to lorewiki"       | User-level SKILL.md not in sync with source        | `Copy-Item` source → user-level; restart session                                              |
| Agent runs `lorewiki` and gets `command not found` | Wheel not installed                               | `uv tool install --editable .` (see §0)                                                          |
| `?` characters in `--raw` JSON on Windows shell      | Pre-v0.1.1 UTF-8 stdout bug (fixed in 0.1.1)     | `uv tool upgrade lorewiki`; or `chcp 65001 | lorewiki ...`                                      |
| Agent picks the wrong wiki path                    | `cwd` has multiple `.lorewiki/config.toml`        | Agent should follow priority chain in SKILL.md §Path Handling; if it fails, paste `--path` explicitly |
| Agent writes Markdown with `Out-File`             | Out-File may add BOM; lorewiki's frontmatter parser fails on BOM | Agent should use `Write` / `Edit` tool, or `[IO.File]::WriteAllText` with UTF-8 no-BOM        |

If you find a new failure mode, open an issue with:
1. `lorewiki --version`
2. The exact agent prompt + agent response
3. The full `lorewiki <failing command>` output

… and the next person to hit the same problem will thank you.
