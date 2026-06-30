<p align="center">
  <img src="../assets/logo.png" alt="LoreWiki" width="320" />
</p>

<p align="center">
  <a href="../README.md">English</a> · <b><a href="README_zh-CN.md">中文</a></b>
</p>

> 面向 LLM 辅助编程的本地优先知识库，基于 SQLite FTS5 实现混合检索。

### 基于

[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-3776AB?logo=python&logoColor=white&style=for-the-badge)](https://www.python.org/)
[![SQLite](https://img.shields.io/badge/SQLite-+FTS5-003B57?logo=sqlite&logoColor=white&style=for-the-badge)](https://www.sqlite.org/)

### 工具

[![uv](https://img.shields.io/badge/uv-pkg%20%2B%20tool-5C2D91?logo=astral&logoColor=white&style=for-the-badge)](https://docs.astral.sh/uv/)
[![ruff](https://img.shields.io/badge/ruff-0%20errors-D7FF64?logo=ruff&logoColor=black&style=for-the-badge)](https://docs.astral.sh/ruff/)
[![pytest](https://img.shields.io/badge/pytest-336%20passed-0A9EDC?logo=pytest&logoColor=white&style=for-the-badge)](../tests/)
[![License](https://img.shields.io/badge/License-MIT-22B14C?style=for-the-badge)](../LICENSE)

---

LoreWiki 把团队的 Markdown wiki 索引到本地 SQLite，并通过单一 CLI 外加一份
[opencode](https://opencode.ai) skill 对外暴露——可被 Codex / Aider / Claude Code
/ 任何能调 shell 的 LLM agent 消费。vault 本身也是一个普通的 `.md` 文件夹，
所以 Obsidian / Logseq / VS Code 都能直接打开。

**示例 wiki 基准数据**（10 个手工标注查询）：

| 模式          | Recall@5 | 平均延迟 |
|---------------|----------|----------|
| BM25          | 80%      | 1.7 ms   |
| Hierarchy     | 90%      | 0.8 ms   |
| **Mix (RRF)** | **100%** | 3.0 ms   |

## 核心特性

- **混合检索**：FTS5 BM25 + 层级树导航，通过 Reciprocal Rank Fusion 融合，无需 score 归一化。
- **中英文友好**：trigram tokenizer + bigram/LIKE 兜底，短中文词（如「幂等」「认证」）也能稳定召回。
- **LLM 可选接入**（Ollama 或 OpenAI 兼容后端）。LLM 离线时优雅降级为「返回 top-K 片段」。
- **单一 CLI + opencode skill**：一个命令入口、一份 opencode skill（或任何能调 shell 的 agent）供 AI 消费，磁盘上的 vault 即「UI」。无服务进程、无额外依赖。
- **一条 `lorewiki add` 完成笔记编写**（body 通过 `--body` / `--file` / stdin 提供），自动增量索引，新文档立即可检索。
- **第二大脑 / 主题（topics）**：在 `~/lorewiki/topics/` 下为每个知识域建一个隔离 vault，跨所有项目共享。
- **零外部服务**：检索仅依赖 SQLite。LLM 完全可选。
- **单包安装**：`pip install lorewiki` 即得一切；数据存放在你的 home 目录，完全归你所有。

## 安装

LoreWiki 是 **PyPI 上的单一 Python wheel**（唯一发布渠道）。任选一个安装器：

### uv（推荐，功能最全）

```bash
# 安装——自动建独立 venv，lorewiki.exe（Windows）或 lorewiki（macOS/Linux）加入 PATH
uv tool install lorewiki

# 装上向量检索可选依赖（sqlite-vec + sentence-transformers）：
uv tool install 'lorewiki[vector]'

# 升级：
uv tool upgrade lorewiki

# 卸载（不会动 ~/.lorewiki/——数据是你的）：
uv tool uninstall lorewiki
```

没有 `uv` 的话：

```bash
# macOS / Linux：
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows（PowerShell）：
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

普通 `pip` 也行（产出的 `lorewiki.exe` 入口相同）：

```bash
pip install lorewiki              # 核心 CLI
pip install 'lorewiki[vector]'    # 可选：向量检索
```

> 0.1.x 的 `[rest]` 和 `[mcp]` extras 在 0.2.0 起已移除。FastAPI / MCP 服务面
> 已由 CLI + opencode skill 取代。`[all]` 现在等价于 `[vector]`。

### 从源码（给贡献者）

```bash
git clone https://github.com/JochenYang/Lore-wiki
cd Lore-wiki
uv tool install --editable .              # dev 安装
uv tool install --editable '.[dev]'       # + pytest / ruff / coverage
```

需要 **Python 3.10+**。装完后 `lorewiki --version` 会输出一个 banner，末尾带 `v0.4.x`。

> **Windows PowerShell + CJK 提醒**：从 0.2.0 起 LoreWiki 强制 stdout/stderr
> 为 UTF-8——CJK 字符在 PowerShell 管道里直接能过，不需要 `chcp 65001`。
> 如果在老版本看到乱码，跑 `uv tool upgrade lorewiki` 或加 `chcp 65001 |` 前缀。

更深的安装细节（PATH 排错、数据位置、备份、常见错误、发布流程）见
[`docs/install.md`](install.md)。

## 快速上手

```bash
# 1. 创建一个 wiki + 样例 Markdown
lorewiki init --path ./my-wiki

# 2. 把 Markdown 索引进 SQLite + FTS5（一次性，之后增量）
lorewiki index --path ./my-wiki

# 3. 检索（默认输出结构化 JSON 喂 agent；加 --human 看 Rich 表格）
lorewiki search "用户登录接口" --path ./my-wiki --mode mix --top-k 5
lorewiki search "用户登录接口" --path ./my-wiki --mode mix --top-k 5 --human

# 4. 智能问答（LLM 辅助生成答案，离线时优雅降级为 top 片段）
lorewiki ask "如何实现幂等重试" --path ./my-wiki

# 5. 从 CLI 写一条笔记（写文件 + 增量索引 一气呵成）
#    body 三种来源，任选其一：
lorewiki add --title "Python Design" --module "patterns" --tag python,design \
    --body "Some deep details about Python design patterns." \
    --path ./my-wiki

#    --file：从文件读 body
lorewiki add --title "From File" --module "patterns" \
    --file ./drafts/python-design.md --path ./my-wiki

#    stdin 管道（Windows + PowerShell 也能用，即使带 CJK；
#    0.2.2+ 会自动清洗 UTF-16 surrogate）
echo "Some deep details about Python design patterns." \
  | lorewiki add --title "From Pipe" --module "patterns" --path ./my-wiki

# 6. 浏览索引 / 层级 / 状态
lorewiki status --path ./my-wiki
lorewiki tree   --path ./my-wiki      # Rich-Tree 视图看层级
lorewiki show   index.md --path ./my-wiki   # 打印一个文档正文（已清洗）
```

**配置优先级**（后写者赢）：

1. `<wiki>/.lorewiki/config.toml` — 单个 wiki 的默认配置
2. `~/.lorewiki/config.toml` — 用户级覆盖
3. `LOREWIKI_*` 环境变量 — shell 级覆盖

任何一层都能用 `lorewiki config list / get / set` 改（TOML 感知，不需要手改文件）。

## 主题（Topics）— 你的第二大脑

上面的 per-wiki 模式适合单项目场景。**共享大脑**用法是 **topics**——在
`~/lorewiki/topics/` 下建多个隔离 vault，从任何项目都能查：

```bash
lorewiki topic create react                              # 空 vault
lorewiki topic create react --source ~/notes/react       # 复制模式（默认）
lorewiki topic create react --source ~/notes/react --link  # 符号链接模式
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

**主题解析优先级**（后者覆盖前者）：`--topic` flag →
`LOREWIKI_TOPIC` env → `~/lorewiki/current` 文件 → `--path`（老 per-wiki
模式）→ cwd 下 `.lorewiki/config.toml`（老 per-project 模式）。

老的 per-project 模式 **永久保留**——无需迁移。主题是便利，不是替代。

vault 根目录就是普通 Markdown + 隐藏 `.lorewiki/`，所以 **Obsidian / Logseq
/ VS Code 都能直接打开**，不需要装 lorewiki。这种跨工具友好正是「第二大脑」
命名的精髓。

主题命名规则：小写 ASCII 字母 + 数字 + `-`，1-64 字符，首尾不能是 `-`。
保留名（`init`、`index`、`current`、Windows 设备名）会被拒绝。

## 工作原理

想看一次完整查询从 CLI dispatch → config 解析 → retriever 选取 → RRF 融合 →
最终输出的端到端走查，**以及 LLM 配置如何生效的深度剖析**（三种配置路径、
`build_client` 工厂分发、为何坚持用纯 `httpx` 而非 SDK），见
[`docs/how-it-works.md`](how-it-works.md)。

更高一层的架构总览在 [`docs/architecture.md`](architecture.md)。各阶段自审
记录在 `docs/critique/phase-{0..6}.md`。

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

> 注意：`set` 的 value 是 **TOML 字面量**——字符串要带引号 `'"bm25"'`，布尔写 `true`/`false`，数字直接写。

## LLM 接入

### Ollama（本地，推荐）

```bash
ollama pull llama3.2
lorewiki config set llm.enabled true     --path ./my-wiki
lorewiki config set llm.backend '"ollama"' --path ./my-wiki
lorewiki ask "what's our retry policy?" --path ./my-wiki
```

### OpenAI 兼容（任何实现 `/v1/chat/completions` 协议的服务）

> **Azure OpenAI 注意事项**：Azure 的路径不同
> （`/openai/deployments/<deployment>/chat/completions?api-version=...`），
> **暂不支持**。请用 OpenRouter 或自部署 vLLM 兼容端点，或等阶段 7 的 Azure
> 支持（如急需可在 issue 提）。

```bash
lorewiki config set llm.enabled true     --path ./my-wiki
lorewiki config set llm.backend '"openai"' --path ./my-wiki
lorewiki config set llm.openai_api_key '"sk-..."' --path ./my-wiki
# 可选：指向兼容代理（OpenRouter、Azure、vLLM……）
lorewiki config set llm.openai_base_url '"https://openrouter.ai/api/v1"' --path ./my-wiki
```

LLM 不可达时，`ask` 会返回 top-K 片段并显式标注 `degraded`——你的工作流不会因为模型掉线而中断。

## REST API

FastAPI / REST 服务面在 0.2.0 已移除。CLI 是唯一的编程入口；agent 通过下文的
opencode skill 消费，或直接 shell out 调用。

## Markdown vault 即你的「UI」

LoreWiki 在 0.1.0 起不再附带内置 Web UI。推荐的消费方式：

- **CLI**（本文档）——唯一事实来源。
- **当前主题的 vault 目录**——每个主题就是 `~/.lorewiki/topics/<名字>/`（per-wiki
  模式下是 `<wiki>/.lorewiki/...`）下的普通 `.md` 文件夹。在 Obsidian、VS Code、
  Cursor 或任何 Markdown 编辑器中打开即可看到完整渲染视图，无需额外工具。
- **opencode skill**（下文）——给 AI agent 用。

## opencode skill（Codex / Aider / 任何能调 shell 的 agent）

对于已经能执行 shell 命令的 agent，直接调 CLI 比 MCP 更轻量。LoreWiki 在
[`skills/lorewiki/SKILL.md`](../skills/lorewiki/SKILL.md) 自带了一份
[opencode](https://opencode.ai) 官方 skill。

一次性安装（先 `uv tool install --editable .` 把 `lorewiki` 加到 PATH）：

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

重启 opencode，agent 会在听到「查 wiki」「search the wiki」「lorewiki ...」等
触发词时自动调用 skill。完整说明见 [`skills/README.md`](../skills/README.md)。

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│            CLI + opencode skill · vault-as-folder          │
├─────────────────────────────────────────────────────────────┤
│  Indexer  │  Retriever (BM25 + Hierarchy + RRF)  │  LLM    │
├─────────────────────────────────────────────────────────────┤
│        SQLite + FTS5 (documents · docs_fts · hierarchy)     │
└─────────────────────────────────────────────────────────────┘
```

完整设计见 `docs/lorewiki dev document.md`，各阶段自我批判见
`docs/critique/phase-{0..6}.md`。最终生产就绪报告见 `docs/production-readiness.md`。

## 开发

```bash
pip install -e ".[dev]"
ruff check lorewiki skills tests  # lint
pytest -q                        # 336 个单元 + 集成测试
pytest --cov=lorewiki            # 覆盖率报告
```

`example_wiki/` 目录是一个精心准备的 5 文件基准 fixture——不是入门样例。
作用与用法见 `example_wiki/README.md`。

## 路线图

- **向量检索**（sqlite-vec + sentence-transformers）——可选，通过
  `pip install lorewiki[vector]` 启用。
- **增量文件监听**（`lorewiki index --watch`，0.3.0 实验性）。
- **PDF / Word 文档导入**（当前仅 Markdown）。
- **`~/lorewiki/current` 的原子写入**（当前是 best-effort）。

## 贡献

流程见 [`CONTRIBUTING.md`](../CONTRIBUTING.md)。Bug 反馈和功能请求走 issue
tracker；欢迎 PR——测试 / lint 命令见上文。

## License

[MIT](../LICENSE) · Copyright (c) 2026 LoreWiki 贡献者。
