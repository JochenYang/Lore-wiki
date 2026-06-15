<p align="center">
  <img src="../assets/logo.png" alt="LoreWiki" width="320" />
</p>

<p align="center">
  <a href="../README.md">English</a> · <b><a href="README_zh-CN.md">中文</a></b>
</p>

> 面向 LLM 辅助编程的本地优先知识库，基于 SQLite FTS5 实现混合检索。

### 基于

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-3776AB?logo=python&logoColor=white&style=for-the-badge)](https://www.python.org/)
[![SQLite](https://img.shields.io/badge/SQLite-+FTS5-003B57?logo=sqlite&logoColor=white&style=for-the-badge)](https://www.sqlite.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-REST-009688?logo=fastapi&logoColor=white&style=for-the-badge)](https://fastapi.tiangolo.com/)
[![MCP](https://img.shields.io/badge/MCP-1.x-1E90FF?logo=modelcontextprotocol&logoColor=white&style=for-the-badge)](https://modelcontextprotocol.io/)

### 工具

[![uv](https://img.shields.io/badge/uv-包%20%2B%20工具-5C2D91?logo=astral&logoColor=white&style=for-the-badge)](https://docs.astral.sh/uv/)
[![ruff](https://img.shields.io/badge/ruff-0%20错误-D7FF64?logo=ruff&logoColor=black&style=for-the-badge)](https://docs.astral.sh/ruff/)
[![pytest](https://img.shields.io/badge/pytest-199%20通过-0A9EDC?logo=pytest&logoColor=white&style=for-the-badge)](tests/)
[![License](https://img.shields.io/badge/License-MIT-22B14C?style=for-the-badge)](LICENSE)

---

LoreWiki 把团队的 Markdown 文档索引到本地 SQLite，并通过 CLI、REST API、MCP 服务对外暴露 — 让 Claude Desktop / Cursor 等 LLM 客户端能在编码时精准检索内部 API 文档、设计模式与踩坑记录。

**示例 Wiki 的基准数据**（10 个手工标注查询）：

| 模式          | Recall@5 | 平均延迟 |
|---------------|----------|----------|
| BM25          | 80%      | 1.7 ms   |
| Hierarchy     | 90%      | 0.8 ms   |
| **Mix (RRF)** | **100%** | 2.6 ms   |

## 核心特性

- **混合检索**：FTS5 BM25 + 层级树状导航，通过 Reciprocal Rank Fusion (RRF) 融合，无需 score 归一化。
- **中英文友好**：trigram tokenizer + bigram/LIKE 兜底，短中文词（如「幂等」「认证」「登录」）也能稳定召回。
- **LLM 可选接入**（Ollama 或 OpenAI 兼容后端）。LLM 离线时优雅降级为「返回 top-K 片段 + 明确提示」，工作流不会被打断。
- **统一内核，三种入口**：CLI、REST（FastAPI）、MCP stdio（用于 Claude Desktop / Cursor 等）；消费知识库的第四种方式是直接在任意 Markdown 编辑器（Obsidian / VS Code / Cursor）中打开当前主题的 vault 目录。
- **零外部服务**：检索仅依赖 SQLite。LLM 完全可选。
- **不需要向量模型**：BM25 + hierarchy 已能达成 Recall@5 = 100%；向量检索作为阶段 6 可选增强。

## 安装

LoreWiki 主推 **PyPI Python wheel**(权威源),同时发布一个 **npm shim** 走同一个 wheel。任选其一:

### Python(推荐,功能最全)

```bash
# 安装——自动建独立 venv,lorewiki.exe(Windows)或 lorewiki(macOS/Linux)加入 PATH
uv tool install lorewiki

# 装上向量检索可选依赖(sqlite-vec + sentence-transformers)
uv tool install 'lorewiki[vector]'

# 升级
uv tool upgrade lorewiki

# 卸载(不会动 ~/.lorewiki/,数据是你的)
uv tool uninstall lorewiki
```

没有 `uv` 的话:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows(PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

普通 `pip` 也行(产出的 `lorewiki.exe` 入口相同):

```bash
pip install lorewiki              # 核心 CLI
pip install 'lorewiki[vector]'    # 可选:向量检索
```

> 0.2.0 砍掉了 0.1.x 的 `[rest]` 和 `[mcp]` extras——FastAPI/MCP 服务面已由
> CLI + opencode skill 取代。`[all]` 现在等价于 `[vector]`。

### Node(npm shim,CLI 行为完全一致)

```bash
npm install -g lorewiki           # postinstall 钩子会调 `uv tool install lorewiki`
npm install -g lorewiki@latest    # 升级
npm uninstall -g lorewiki         # 同时调 `uv tool uninstall lorewiki`
```

npm 包只是 shim,真正干活的是 postinstall 装好的 Python `lorewiki`。详见 [`README.npm.md`](../README.npm.md)。

### 从源码(给贡献者)

```bash
git clone https://github.com/JochenYang/Lore-wiki
cd Lore-wiki
uv tool install --editable .              # dev 模式
uv tool install --editable '.[dev]'       # + pytest / ruff / coverage
```

需要 **Python 3.10+**。装完后 `lorewiki --version` 会输出一个 banner,末尾带 `v0.2.x`。

> **Windows PowerShell + CJK 提醒**:从 0.2.0 开始 LoreWiki 强制 stdout/stderr
> 为 UTF-8,CJK 字符在 PowerShell 管道里直接能过,不需要 `chcp 65001`。
> 如果老版本看到乱码,跑 `uv tool upgrade lorewiki` 或者临时加 `chcp 65001 |` 前缀。

更深的安装细节(PATH 排错、数据位置、备份、常见错误、发布流程)见 [`docs/install.md`](install.md)。

## 快速上手(5 分钟)

```bash
# 1. 创建一个新 wiki + 样例 Markdown
lorewiki init --path ./my-wiki

# 2. 把 Markdown 索引进 SQLite + FTS5(一次性,之后增量)
lorewiki index --path ./my-wiki

# 3. 检索(默认输出 JSON 喂 agent,加 --human 看 Rich 表格)
lorewiki search "用户登录接口" --path ./my-wiki --mode mix --top-k 5
lorewiki search "用户登录接口" --path ./my-wiki --mode mix --top-k 5 --human

# 4. 智能问答(未装 LLM 时自动降级为返回 top-K 片段 + 提示)
lorewiki ask "如何实现幂等重试" --path ./my-wiki

# 5. 从 CLI 写一条笔记(写文件 + 增量索引 一气呵成)
#    body 三种来源,任选其一:
lorewiki add --title "幂等设计" --module "patterns" --tag retry,idempotency \
    --body "幂等设计 (Idempotency-Key 模式) 用于防止重复扣款与重试导致的双写。" \
    --path ./my-wiki

#    --file: 从文件读 body
lorewiki add --title "从文件来" --module "patterns" \
    --file ./drafts/python-design.md --path ./my-wiki

#    stdin pipe(Windows + PowerShell 也能用,即使带 CJK;
#    0.2.2+ 会自动清洗 UTF-16 surrogate)
echo "幂等设计 (Idempotency-Key 模式) 用于防止重复扣款。" \
  | lorewiki add --title "从管道来" --module "patterns" --path ./my-wiki

# 6. 状态/层级/正文浏览
lorewiki status --path ./my-wiki
lorewiki tree   --path ./my-wiki      # Rich-Tree 视图看层级
lorewiki show   index.md --path ./my-wiki   # 打印一个文档(已清洗)
```

**配置优先级**(后写者赢):

1. `<wiki>/.lorewiki/config.toml` — 单个 wiki 的默认配置
2. `~/.lorewiki/config.toml` — 用户级覆盖
3. `LOREWIKI_*` 环境变量 — shell 级覆盖

任何一层都能用 `lorewiki config list / get / set` 改(TOML 感知,不需要手改文件)。

## 主题（Topic）— 你的「共享大脑」

上面的 per-wiki 模式适合单项目场景。**真正的「本地知识库 / 共享大脑」用法是用主题** — 在 `~/lorewiki/topics/` 下建多个隔离 vault，从任何项目都能查：

```bash
lorewiki topic create react                              # 空 vault
lorewiki topic create react --source ~/notes/react       # 复制源（默认）
lorewiki topic create react --source ~/notes/react --link  # 符号链接（源不动）
lorewiki topic use react                                 # 激活
lorewiki index                                           # 索引当前主题
lorewiki search "useState closure"                       # 查当前主题
lorewiki ask "props drilling 对比"                       # LLM 从当前主题回答
```

生成的目录结构：

```
~/lorewiki/                          # 中央根
├── config.toml                      # 全局：LLM key、retrieval mode
├── current                          # 文本文件：当前激活的主题名
└── topics/
    └── react/                       # 一个主题 = 一个 vault
        ├── .lorewiki/index.db       # 隐藏的 lorewiki 元数据
        ├── api/auth.md
        └── architecture.md
```

**主题解析优先级**（后者覆盖前者）：`--topic` flag → `LOREWIKI_TOPIC` env → `~/lorewiki/current` 文件 → `--path`（老 per-wiki 模式）→ cwd 下 `.lorewiki/config.toml`（老 per-project 模式）。

**老的 per-project 模式永久保留**，无需迁移 — 主题是便利，不是替代。

vault 根目录就是普通 Markdown + 隐藏 `.lorewiki/`，所以 **Obsidian / Logseq / VS Code 都能直接打开**，不需要装 lorewiki — 这就是「共享大脑」的精髓：你的数据归你，不被任何工具锁死。

主题命名规则：小写 ASCII 字母 + 数字 + `-`，1-64 字符，首尾不能是 `-`。保留名（`init` / `index` / `current`、Windows 设备名）会被拒绝。

## 工作原理

想看一次完整查询从 CLI dispatch 到 config 解析、retriever 选取、RRF 融合、
最终输出的端到端走查，**以及 LLM 配置如何生效的深度剖析**（三种配置路径、
`build_client` 工厂分发、为何坚持用纯 `httpx` 而非 SDK），请见
[`docs/how-it-works.md`](docs/how-it-works.md)。

更高一层的架构总览在 [`docs/architecture.md`](docs/architecture.md)。
各阶段自审记录见 `docs/critique/phase-{0..6}.md`。

## 配置说明

```toml
# ./my-wiki/.lorewiki/config.toml

retrieval_mode = "mix"            # mix | bm25 | hierarchy | vector
rrf_k = 60                        # RRF 平滑常数（标准取 60）
chunk_max_tokens = 800            # 单个 chunk 最大 token（估算）
chunk_overlap_tokens = 100        # 超大块切分时的重叠 token
chunk_min_chars = 40              # 小于此长度的 chunk 会被合并
snippet_chars = 240               # 检索结果片段长度

[mix_weights]                     # 各检索器的 RRF 权重
bm25 = 1.0
hierarchy = 0.8
vector = 0.5

[llm]
enabled = false                   # 设为 true 才会调用 LLM 生成答案
backend = "ollama"                # ollama | openai
ollama_url = "http://localhost:11434"
ollama_model = "llama3.2"         # 也可以是 qwen2.5 / mistral / etc.
openai_api_key = ""
openai_base_url = ""              # 留空走官方 api.openai.com
openai_model = "gpt-4o-mini"
timeout_seconds = 30.0
```

通过 CLI 改配置：

```bash
lorewiki config list --path ./my-wiki
lorewiki config get llm.backend --path ./my-wiki
lorewiki config set retrieval_mode '"bm25"' --path ./my-wiki
```

> 注意：`set` 的 value 是 **TOML 字面量**，字符串要带引号 `'"bm25"'`，布尔写 `true`/`false`，数字直接写。

## LLM 接入（**仅需 chat model，无需向量模型**）

### Ollama（本地，推荐）

```bash
# 1. 装 Ollama: https://ollama.com/download
# 2. 拉一个模型（任意 chat / instruct 模型都行）
ollama pull llama3.2          # 英文为主
# 或者 中文友好：
ollama pull qwen2.5:7b

# 3. 开启 LLM
lorewiki config set llm.enabled true --path ./my-wiki
lorewiki config set llm.backend '"ollama"' --path ./my-wiki
lorewiki config set llm.ollama_model '"qwen2.5:7b"' --path ./my-wiki

# 4. 问答
lorewiki ask "我们的重试策略是什么？" --path ./my-wiki
```

### OpenAI 兼容（任何实现 /v1/chat/completions 协议的服务）

> **Azure OpenAI 注意事项**：Azure 的 endpoint 路径是 /openai/deployments/<deployment>/chat/completions?api-version=...，
与 lorewiki 当前硬编码的路径不一致，**暂不支持**。请用 OpenRouter 或自部署 vLLM
兼容端点；如需 Azure 支持请在 issue 提，或等阶段 7 路线图。

```bash
lorewiki config set llm.enabled true              --path ./my-wiki
lorewiki config set llm.backend '"openai"'         --path ./my-wiki
lorewiki config set llm.openai_api_key '"sk-..."'  --path ./my-wiki
lorewiki config set llm.openai_model '"gpt-4o-mini"' --path ./my-wiki
# 可选：换代理 URL
lorewiki config set llm.openai_base_url '"https://openrouter.ai/api/v1"' --path ./my-wiki
```

LLM 不可达时（网络问题 / 配置错 / 没装），`ask` 会返回 top-K 检索片段并显式标注 `degraded` 状态 — **不会卡死也不会报 500**。

## REST API

```bash
lorewiki rest --port 8000 --path ./my-wiki
# Swagger UI:    http://127.0.0.1:8000/docs
# OpenAPI JSON:  http://127.0.0.1:8000/openapi.json
```

| 方法 | 路径                  | 说明                                             |
|------|-----------------------|--------------------------------------------------|
| GET  | `/health`             | 健康检查 (`{"status": "ok"}`)                    |
| GET  | `/status`             | 索引统计（chunks / docs / 最后索引时间 / DB 大小） |
| POST | `/search`             | `{query, top_k, mode}` → 排序后的 hits           |
| POST | `/ask`                | `{query, top_k}` → 答案 + 引用                   |
| GET  | `/modules`            | 顶层模块列表                                     |
| GET  | `/module/{path:path}` | 模块子树展开                                     |

示例：

```bash
curl -X POST http://127.0.0.1:8000/search `
  -H "Content-Type: application/json" `
  -d '{"query": "幂等设计", "top_k": 3, "mode": "mix"}'
```

## REST API 与 vault 目录（替代原 Web UI）

```powershell
lorewiki -t wechat-miniprogram-api rest --port 8000
# Swagger UI:    http://127.0.0.1:8000/docs
# OpenAPI JSON:  http://127.0.0.1:8000/openapi.json
```

LoreWiki 在 0.1.0 不再附带内置 Web UI。推荐使用以下三种方式消费知识库：

- **REST API**（上）— 完整 OpenAPI 接口，可被任何 HTTP 客户端调用。
- **MCP stdio 服务器** — 把 lorewiki 接入 Claude Desktop / Cursor / opencode / Codex 作为模型可调用的工具。
- **当前主题的 vault 目录** — 每个主题就是 `~/.lorewiki/topics/<名字>/` 下的普通 `.md` 文件夹（在 per-wiki 模式下是 `<wiki>/.lorewiki/...`）。在 Obsidian / VS Code / Cursor 等任何 Markdown 编辑器中直接打开，就能看到完整渲染视图，不需要任何额外工具。

## MCP 服务（Claude Desktop / Cursor）

```bash
lorewiki mcp --path ./my-wiki
```

在 Claude Desktop 的配置文件里加：

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "lorewiki": {
      "command": "lorewiki",
      "args": ["mcp", "--path", "D:/absolute/path/to/my-wiki"]
    }
  }
}
```

暴露的工具：
- `search_lorewiki(query, top_k=5, mode="mix")` — 返回排序后的 chunks
- `get_module_summary(module_path="")` — 探查层级树（空串表示 root）

重启 Claude Desktop 后，新对话中 LLM 能自动调用这两个工具检索 wiki。

## opencode skill（Codex / Aider / 任何能调 shell 的 Agent）

对于已经能执行 shell 命令的 Agent，直接调 CLI 比 MCP 更轻量。LoreWiki 在
[`skills/lorewiki/SKILL.md`](skills/lorewiki/SKILL.md) 自带了一份
[opencode](https://opencode.ai) 官方 skill。

一次性安装（先确保 `lorewiki` 在 PATH 里，推荐用 `uv tool install --editable . --with fastapi --with "uvicorn[standard]" --with mcp`）：

```powershell
# Windows
.\skills\install.ps1            # 复制模式
.\skills\install.ps1 -Symlink   # 符号链接模式（编辑 SKILL.md 实时生效）
```

```bash
# macOS / Linux
./skills/install.sh             # 复制模式
./skills/install.sh --symlink   # 符号链接模式
```

重启 opencode 即可。Agent 会在听到「查 wiki」「search the wiki」「lorewiki ...」
这类触发词时自动调用 skill。完整说明见
[`skills/README.md`](skills/README.md)。

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│           CLI · REST · MCP stdio · vault-as-folder        │
├─────────────────────────────────────────────────────────────┤
│  Indexer  │  Retriever (BM25 + Hierarchy + RRF)  │  LLM    │
├─────────────────────────────────────────────────────────────┤
│        SQLite + FTS5 (documents · docs_fts · hierarchy)     │
└─────────────────────────────────────────────────────────────┘
```

完整设计见 `docs/lorewiki开发文档.md`，每阶段自我批判见 `docs/critique/phase-{0..5}.md`，最终生产就绪报告见 `docs/production-readiness.md`。

## 开发

```bash
pip install -e ".[dev]"

ruff check lorewiki tests        # 静态检查（当前 0 错误）
pytest -q                        # 115 个单元/集成测试
pytest --cov=lorewiki            # 测试覆盖率（核心 92%）
```

跑 Recall 基准（需要 `example_wiki/`）：

```bash
python scripts/recall_phase2.py  # BM25 vs Hierarchy vs Mix 三模式对比
```

## 路线图

- **向量检索**（sqlite-vec + sentence-transformers）— 可选启用
- **异步 LLM 客户端** — 让 REST `/ask` 支持并发
- **流式 `/ask` 端点**（SSE）— 长答案实时展示
- **增量文件监听**（`lorewiki update --watch`）
- **PDF / Word 文档导入**（当前仅 Markdown）

## 贡献

流程见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。Bug 反馈和功能请求走 issue tracker；
欢迎 PR — 测试 / lint 命令见上文。

## License

[MIT](LICENSE) · Copyright (c) 2026 LoreWiki 贡献者。
