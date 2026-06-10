# LoreWiki 开发方案

## 1. 项目概述

LoreWiki 是一个面向开发团队的本地/轻量云知识库系统，专为 LLM 辅助编程设计。它通过混合检索（传统关键词 + 推理式导航）让大模型在编码时能精准调用团队内部 API 文档、代码模式与踩坑记录。核心交付物为 **CLI 工具**，同时提供可选的 Web UI 与 MCP 服务。

### 1.1 核心目标
- 零外部依赖的本地检索（SQLite FTS5 为基础）
- 支持 LLM 可选集成（Ollama / OpenAI）进行查询改写与层级导航
- 通过 CLI 直接使用，同时暴露 MCP 协议供 Claude Desktop / Cursor 调用
- 轻量可视化（Streamlit）用于文档浏览与配置管理

### 1.2 非目标
- 不替代企业级 Wiki（如 Confluence）
- 不强制使用向量数据库（向量检索作为可选增强）
- 不提供多用户权限系统（单机或团队共享部署）

---

## 2. 技术栈

| 类别 | 选型 | 说明 |
|------|------|------|
| 语言 | Python 3.10+ | 生态丰富，CLI/MCP/RAG 成熟 |
| 数据库 | SQLite + FTS5 | 内置零配置，全文检索性能优异 |
| 可选向量扩展 | sqlite-vec | 轻量级向量检索，按需启用 |
| 传统检索 | FTS5 + RRF | 融合 BM25 风格排序 |
| 推理式检索 | 自研层级索引 | 基于目录树 + 可选 LLM 导航 |
| CLI 框架 | typer | 现代、类型提示、自动帮助文档 |
| Web UI | Streamlit | 极简代码实现可视化 |
| MCP SDK | mcp (Python) | 官方协议，供 LLM 客户端调用 |
| REST API (可选) | FastAPI + Uvicorn | 对外提供 HTTP 接口 |
| LLM 集成 | Ollama / OpenAI | 本地优先，支持配置切换 |
| 配置管理 | pydantic-settings | 环境变量 / .env / config.toml |
| 日志 | loguru | 结构化输出，便于调试 |
| 包管理 | uv / pip + pyproject.toml | 现代 Python 打包 |

---

## 3. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                         用户入口                            │
│  ┌──────────┐  ┌──────────┐  ┌─────────────────────────┐  │
│  │   CLI    │  │  Web UI  │  │ MCP Server (stdio)      │  │
│  └────┬─────┘  └────┬─────┘  └──────┬──────────────────┘  │
│       └─────────────┼───────────────┘                       │
└─────────────────────┼───────────────────────────────────────┘
                      │ 调用统一 Core API
┌─────────────────────▼───────────────────────────────────────┐
│                    LoreWiki Core                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  索引管理器 (Indexer)                                 │   │
│  │  • Markdown 解析 & 分块                               │   │
│  │  • 写入 SQLite + FTS5                                 │   │
│  │  • 构建层级索引表 (hierarchy)                         │   │
│  │  • (可选) 生成向量并存入 sqlite-vec                   │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  检索引擎 (Retriever)                                 │   │
│  │  • BM25Retriever (基于 FTS5)                          │   │
│  │  • HierarchyRetriever (推理式，支持 LLM 导航)         │   │
│  │  • VectorRetriever (可选，sqlite-vec)                 │   │
│  │  • 融合器: RRF (Reciprocal Rank Fusion)              │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  LLM 服务 (可选)                                      │   │
│  │  • 查询改写 (Query Rewriting)                         │   │
│  │  • 层级导航决策                                       │   │
│  │  • 最终答案生成 (Generator)                           │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                   数据存储 (SQLite)                          │
│   • documents    原始文档表                                  │
│   • docs_fts     FTS5 虚拟表                                │
│   • hierarchy    层级索引表                                  │
│   • vectors      向量表 (可选)                               │
│   • config       配置表                                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. 数据库设计

### 4.1 表结构

```sql
-- 文档原始数据表
CREATE TABLE documents (
    id TEXT PRIMARY KEY,           -- UUID or 文件路径哈希
    path TEXT NOT NULL UNIQUE,     -- 文件绝对路径或相对路径
    title TEXT,
    content TEXT NOT NULL,         -- 清洗后的纯文本或 Markdown 原文
    module TEXT,                   -- 一级模块名，如 "api/user"
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- FTS5 全文检索表 (内容由 documents 表同步，使用触发器)
CREATE VIRTUAL TABLE docs_fts USING fts5(
    title, content, module,
    content=documents               -- 关联外部内容表
);

-- 触发器：自动同步 documents 到 fts
CREATE TRIGGER documents_ai AFTER INSERT ON documents BEGIN
    INSERT INTO docs_fts(rowid, title, content, module)
    VALUES (new.id, new.title, new.content, new.module);
END;
CREATE TRIGGER documents_ad AFTER DELETE ON documents BEGIN
    INSERT INTO docs_fts(docs_fts, rowid, title, content, module) 
    VALUES('delete', old.id, old.title, old.content, old.module);
END;
CREATE TRIGGER documents_au AFTER UPDATE ON documents BEGIN
    INSERT INTO docs_fts(docs_fts, rowid, title, content, module) 
    VALUES('delete', old.id, old.title, old.content, old.module);
    INSERT INTO docs_fts(rowid, title, content, module)
    VALUES (new.id, new.title, new.content, new.module);
END;

-- 层级索引表 (推理式检索核心)
CREATE TABLE hierarchy (
    id TEXT PRIMARY KEY,            -- 路径哈希或 UUID
    parent_id TEXT,                 -- 父节点 ID，根节点为 NULL
    node_type TEXT NOT NULL,        -- 'module' | 'api' | 'section' | 'doc'
    title TEXT NOT NULL,
    summary TEXT,                   -- 该节点摘要（自动生成或手动）
    path TEXT NOT NULL UNIQUE,      -- 如 "api/user/auth"
    level INTEGER NOT NULL,         -- 深度，根节点为 0
    doc_id TEXT,                    -- 若节点对应具体文档，关联 documents.id
    FOREIGN KEY(parent_id) REFERENCES hierarchy(id),
    FOREIGN KEY(doc_id) REFERENCES documents(id)
);

-- 可选：向量存储 (使用 sqlite-vec 扩展)
-- 需先加载扩展
CREATE VIRTUAL TABLE vectors USING vec0(
    id TEXT PRIMARY KEY,            -- 对应 documents.id
    embedding FLOAT[384]            -- 维度取决于模型
);
```

### 4.2 索引优化
- `documents(path)` 唯一索引
- `hierarchy(path)` 唯一索引
- `hierarchy(parent_id)` 外键索引

---

## 5. 核心模块详细设计

### 5.1 文档解析与分块 (Indexer)

**输入**：本地目录（如 `~/lorewiki/`）或单个 Markdown 文件  
**处理流程**：
1. 扫描所有 `.md` 文件，忽略 `.git`, `__pycache__` 等目录。
2. 解析 YAML Frontmatter (可选)，提取 `title`, `module` 等元数据。
3. 按 `##` 二级标题切分块（chunk），每个块保留上下文：`标题路径` + `内容`。
4. 每个块作为一条独立的 `documents` 记录，`id` 生成规则：`文件路径哈希 + 块序号`。
5. 构建层级索引：
   - 从文件路径和标题自动推断层级结构（例如 `api/user/auth.md` → 路径 `api/user/auth`）。
   - 每个节点插入 `hierarchy` 表，自动生成摘要（取前 200 字符作为 `summary`）。
6. 若配置启用了向量检索，调用 embedding 模型生成向量，存入 `vectors` 表。

**命令行**：`lorewiki index [--path PATH] [--rebuild]`

### 5.2 检索引擎

#### 5.2.1 BM25Retriever (传统)
- 基于 FTS5 的 `MATCH` 查询：`SELECT rowid, rank, title, snippet(content) FROM docs_fts WHERE docs_fts MATCH ? ORDER BY rank LIMIT ?`
- `rank` 列由 FTS5 自动计算（类似 BM25），无需额外处理。
- 返回字段包含 `id`, `title`, `content_snippet`, `score`。

#### 5.2.2 HierarchyRetriever (推理式)
**核心思想**：将检索视为在树状索引上的多步导航，可完全无 LLM 也可由 LLM 辅助决策。

**无 LLM 版本**（默认）：
- 接收用户查询 `q`，在 `hierarchy` 表的 `title` 和 `summary` 列上进行关键词匹配（FTS5 或简单的 `LIKE`）。
- 找到匹配度最高的节点，然后递归返回其所有子节点对应的文档块。

**LLM 增强版本**（可选配置）：
- 从根节点开始，调用 LLM 传入当前节点的子节点列表（标题+摘要）和用户问题，让 LLM 选择最相关的子节点。
- 迭代直到叶子节点，然后返回该节点下的所有文档块。
- 如果 LLM 不可用或判断失败，自动降级为关键词匹配。

#### 5.2.3 VectorRetriever (可选)
- 使用 `sqlite-vec` 扩展，执行余弦相似度搜索：`SELECT id, distance FROM vectors WHERE embedding MATCH ? AND k = ?`
- 需提前配置 embedding 模型（如 `sentence-transformers/all-MiniLM-L6-v2`）。

#### 5.2.4 融合器 (Fusion)
- 采用 **RRF (Reciprocal Rank Fusion)** 合并多个检索器结果。
- 公式：`score(d) = Σ (1 / (k + rank_i(d)))`，其中 `k` 通常取 60。
- 支持为不同检索器分配权重（加权 RRF）。

### 5.3 LLM 集成服务

支持两种后端：
- **Ollama**（本地，推荐）：`ollama pull llama3.2` 等。
- **OpenAI API**：需提供 `api_key` 和 `base_url`。

**功能模块**：
1. **查询改写**：当 BM25/Hierarchy 检索结果为空或相关性评分低于阈值时，调用 LLM 生成 1-3 个替代查询，再重新检索。
2. **层级导航决策**：如上文 HierarchyRetriever 所述，LLM 作为选择器。
3. **答案生成**：将检索到的文档块作为上下文 + 用户问题，调用 LLM 生成最终答案（用于 `lorewiki ask` 命令）。

### 5.4 CLI 命令设计

使用 `typer` 实现，所有命令支持 `--help`。

```bash
# 初始化
lorewiki init [--path PATH]               # 创建配置文件和示例文档

# 索引管理
lorewiki index [--path PATH] [--rebuild]  # 索引指定目录（默认当前配置路径）
lorewiki status                           # 显示索引统计（文档数、最后索引时间）
lorewiki update [--watch]                 # 增量索引（可监听文件变化）

# 检索与问答
lorewiki search QUERY [--top-k 5] [--mode mix]   # mix | bm25 | hierarchy | vector
lorewiki ask QUERY [--model ollama]              # 检索 + LLM 生成答案

# 配置
lorewiki config list                            # 列出当前配置
lorewiki config set KEY VALUE                   # 设置配置项
lorewiki config get KEY

# 服务启动
lorewiki ui [--port 8501]                       # 启动 Streamlit Web UI
lorewiki mcp                                    # 启动 MCP stdio 服务
lorewiki rest [--port 8000]                     # 启动 REST API (可选)
```

### 5.5 配置文件

默认位置：`~/.lorewiki/config.toml`，同时支持项目级 `.lorewiki/config.toml`。

```toml
# Wiki 根目录
wiki_path = "~/my-wiki"

# 检索引擎
retrieval_mode = "mix"   # mix | bm25 | hierarchy | vector
mix_weights = { bm25 = 1.0, hierarchy = 0.8, vector = 0.5 }
rrf_k = 60

# LLM 配置
[llm]
enabled = true
backend = "ollama"       # ollama | openai
ollama_url = "http://localhost:11434"
ollama_model = "llama3.2"
openai_api_key = ""
openai_base_url = ""
openai_model = "gpt-4o-mini"

# 向量检索（可选）
[vector]
enabled = false
embedding_model = "all-MiniLM-L6-v2"
embedding_dim = 384
```

### 5.6 Web UI (Streamlit)

页面结构：
- **搜索页**：输入框 + 模式选择（Mix/BM25/Hierarchy）+ 结果列表（可展开查看文档片段）。
- **浏览页**：侧边栏显示层级树，主区域渲染 Markdown 文档。
- **配置页**：动态修改配置（LLM 后端、检索权重等），无需重启。
- **状态页**：索引统计、数据库大小、最后索引时间。

启动命令：`lorewiki ui` 自动打开浏览器。

### 5.7 MCP 服务

使用 `mcp` Python SDK 实现，暴露以下工具（tools）：

```python
# lorewiki/mcp_server.py
from mcp.server import Server, stdio_server
from mcp.types import Tool, TextContent

tools = [
    Tool(
        name="search_lorewiki",
        description="在 LoreWiki 知识库中搜索相关文档片段",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词或问题"},
                "top_k": {"type": "integer", "default": 5},
                "mode": {"type": "string", "enum": ["mix", "bm25", "hierarchy"]}
            },
            "required": ["query"]
        }
    ),
    Tool(
        name="get_module_summary",
        description="获取某个模块的层级摘要信息",
        inputSchema={
            "type": "object",
            "properties": {
                "module_path": {"type": "string", "description": "如 'api/user'"}
            },
            "required": ["module_path"]
        }
    )
]

# 实现处理函数...
```

启动后，在 Claude Desktop 配置文件中添加：
```json
{
  "mcpServers": {
    "lorewiki": {
      "command": "lorewiki",
      "args": ["mcp"]
    }
  }
}
```

### 5.8 REST API (可选)

使用 FastAPI 实现，提供 OpenAPI 文档（`/docs`）。

| 端点 | 方法 | 说明 |
|------|------|------|
| `/search` | POST | 检索文档片段，参数 `{query, top_k, mode}` |
| `/ask` | POST | 检索 + LLM 生成答案 |
| `/modules` | GET | 列出所有顶级模块 |
| `/module/{path}` | GET | 获取模块详情及子节点 |
| `/status` | GET | 索引状态 |

---

## 6. 开发阶段与交付物

### 阶段 0：环境搭建 (1天)
- 创建 Python 项目，配置 `pyproject.toml`，使用 `uv` 或 `pip` 管理依赖。
- 搭建 CLI 骨架（typer），实现 `--version` 和 `--help`。
- 配置日志（loguru）。

### 阶段 1：核心索引与检索（5天）
- 实现 Markdown 解析、分块，写入 SQLite + FTS5。
- 实现 `lorewiki index` 和 `lorewiki search --raw`。
- 单元测试：索引 10 个样例文档，验证 BM25 检索结果。

### 阶段 2：推理式检索（4天）
- 构建 `hierarchy` 表，实现从目录结构和文档标题自动填充。
- 实现 HierarchyRetriever（无 LLM 版）。
- 实现 RRF 融合器，支持 BM25 + Hierarchy 混合检索。
- CLI 增加 `--mode` 选项。

### 阶段 3：LLM 集成（3天）
- 实现 LLM 客户端（Ollama / OpenAI 抽象）。
- 实现查询改写和答案生成。
- CLI 实现 `lorewiki ask` 命令。
- 可选：为 HierarchyRetriever 增加 LLM 导航（作为配置开关）。

### 阶段 4：可视化与 API（4天）
- 实现 Streamlit UI（搜索页、浏览页、配置页、状态页）。
- 实现 REST API（FastAPI）。
- CLI 增加 `ui`, `rest` 子命令。

### 阶段 5：MCP 服务与打包（2天）
- 实现 MCP Server 并集成到 CLI (`lorewiki mcp`)。
- 编写使用文档（Markdown）。
- 打包发布到 PyPI（`lorewiki` 包名）。
- 准备示例 Wiki 仓库（示例 API 文档）。

### 阶段 6：可选增强（后续迭代）
- 向量检索支持（`sqlite-vec` + sentence-transformers）。
- 增量监听（watchdog）。
- 支持导入已有 Markdown 文档库。
- 支持 PDF / Word 文档。

---

## 7. 安装与使用示例

### 7.1 安装
```bash
pip install lorewiki
# 或使用 uv
uv tool install lorewiki
```

### 7.2 初始化
```bash
lorewiki init --path ~/my-wiki
cd ~/my-wiki
# 编写 Markdown 文档，按目录组织
```

### 7.3 索引与搜索
```bash
lorewiki index
lorewiki search "用户登录接口" --mode mix
lorewiki ask "如何实现幂等重试？"
```

### 7.4 启动服务
```bash
# Web UI
lorewiki ui

# MCP (供 Claude Desktop 使用)
lorewiki mcp
```

---

## 8. 项目结构

```
lorewiki/
├── pyproject.toml
├── README.md
├── lorewiki/
│   ├── __init__.py
│   ├── cli.py                 # typer 命令入口
│   ├── config.py              # 配置管理
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py      # SQLite 连接管理
│   │   ├── schema.sql         # 建表语句
│   │   └── models.py          # 数据类定义
│   ├── indexer/
│   │   ├── __init__.py
│   │   ├── parser.py          # Markdown 解析
│   │   ├── chunker.py         # 分块逻辑
│   │   └── indexer.py         # 索引主流程
│   ├── retriever/
│   │   ├── __init__.py
│   │   ├── bm25.py
│   │   ├── hierarchy.py
│   │   ├── vector.py          # 可选
│   │   └── fusion.py          # RRF
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py          # Ollama/OpenAI 封装
│   │   └── generator.py
│   ├── server/
│   │   ├── mcp_server.py
│   │   ├── rest_api.py
│   │   └── ui.py              # Streamlit 应用
│   └── utils/
│       ├── logger.py
│       └── file_watcher.py
├── tests/
│   ├── test_indexer.py
│   ├── test_retriever.py
│   └── fixtures/
│       └── sample_wiki/
└── example_wiki/              # 示例知识库
    ├── index.md
    ├── api/
    │   └── user/
    │       └── auth.md
    └── patterns/
        └── retry.md
```

---

## 9. 验收标准

1. **CLI 功能**：
   - `lorewiki init` 可创建配置文件及示例目录。
   - `lorewiki index` 能在 1 秒内索引 100 个文档（每文档 5KB）。
   - `lorewiki search "xxx"` 返回 top_k 片段，延迟 < 200ms。
   - `lorewiki ask "xxx"` 在 Ollama 本地模型下，端到端延迟 < 5s。

2. **检索质量**：
   - 在人工标注的 50 个 API 查询测试集上，混合模式（mix）的 Recall@5 ≥ 0.85。
   - 纯 BM25 模式在精确术语查询上 Recall@5 ≥ 0.95。

3. **可视化**：
   - Web UI 可在浏览器正常使用，支持搜索、文档浏览、配置修改。

4. **MCP 服务**：
   - Claude Desktop 能够调用 `search_lorewiki` 工具并返回有效结果。

5. **打包分发**：
   - `pip install lorewiki` 后，所有命令可执行，无缺失依赖。

---

## 10. 维护与扩展指南

- **增加新的文档格式**：在 `indexer/parser.py` 中添加对应解析器，注册到 `SUPPORTED_EXTENSIONS`。
- **替换检索引擎**：实现 `BaseRetriever` 接口，并在 `fusion.py` 中注册。
- **自定义 LLM 后端**：继承 `BaseLLMClient`，实现 `generate` 和 `embed` 方法。
- **数据库迁移**：在 `db/migrations/` 下存放版本化 SQL 脚本，启动时自动检查并迁移。

---

**文档版本**：1.0  
**最后更新**：2026-06-10