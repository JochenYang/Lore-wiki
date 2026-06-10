---
title: LoreWiki 示例知识库
module: root
tags: [overview, index, navigation]
---

# LoreWiki 示例知识库

本仓库为 LoreWiki 的示例 Wiki，演示如何按 **模块 / 子模块 / 文档** 三级组织通用后端服务的内部知识。所有 Markdown 文件均遵循统一规范，便于被 LoreWiki 索引器自动解析并构建层级检索树。

## 文档结构约定

每篇文档必须包含以下要素，以便检索器抽取元数据：

1. **YAML Frontmatter**：声明 `title`、`module`、`tags`，是 hierarchy 节点的核心信息源。
2. **二级标题分块**：每个 `##` 段落作为独立检索块，建议覆盖「概述 / 接口 / 参数 / 示例 / 错误码 / 踩坑」六类内容。
3. **代码示例**：使用三反引号围栏并标注语言，避免被分块器误判为正文。
4. **错误码表**：固定使用 Markdown 表格，便于结构化抽取。

## 模块导航

本示例 Wiki 当前包含两个一级模块：

### api/ — 业务接口文档

- [`api/user/auth`](api/user/auth.md) — 用户认证：登录、登出、Token 刷新。
- [`api/order/checkout`](api/order/checkout.md) — 订单下单：库存校验、优惠券、幂等设计。

`api/` 下的文档命名遵循 `资源/动作` 模式，URL 路径与文档路径保持一致，便于跨索引检索时的关键词命中。

### patterns/ — 设计模式与最佳实践

- [`patterns/retry`](patterns/retry.md) — 重试策略与幂等设计，包含指数退避、抖动、反模式。
- [`patterns/rate-limit`](patterns/rate-limit.md) — 限流方案选型：令牌桶、漏桶、分布式实现。

`patterns/` 下的文档以「问题描述 → 方案对比 → 代码示例 → 选型建议」结构组织，便于在 LLM 辅助编码时直接复用。

## 检索使用建议

以下查询是验证检索质量的典型样本，建议在阶段 1 / 2 完成后逐一回归：

| 查询 | 期望命中文档 | 检索难点 |
|------|-------------|---------|
| 用户登录接口 | `api/user/auth` | 精确术语匹配 |
| JWT 刷新策略 | `api/user/auth` | 跨段落语义聚合 |
| 如何实现幂等重试 | `patterns/retry` + `api/order/checkout` | 跨模块召回 |
| 限流方案选型 | `patterns/rate-limit` | 长尾关键词 |
| 下单库存超卖 | `api/order/checkout` | 同义词扩展 |

## 维护规范

- **新增模块**：在根目录下新建子目录，并在本文件「模块导航」一节同步追加入口。
- **修改文档**：保持 frontmatter 中的 `module` 字段与目录路径一致，避免 hierarchy 表脏数据。
- **删除文档**：删除前需检查交叉引用（建议先在 LoreWiki 中搜索文件名）。

## 关联资源

- LoreWiki 开发文档：`docs/lorewiki开发文档.md`
- 索引命令：`lorewiki index --path ./example_wiki`
- 测试查询：`lorewiki search "用户登录接口" --mode mix`
