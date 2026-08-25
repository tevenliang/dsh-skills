# Init Templates — 初始化页面模板（vault 版）

初始化知识库时用于创建 AGENTS.md、INDEX.md、LOG.md 三个文件的骨架模板。模板中 `{{...}}` 为占位符。

> 页面类型定义: [wiki-schema.md](../wiki-schema.md)

---

## AGENTS.md 模板

**标题**: `AGENTS`
**存放**: 根目录 `<wiki-name>/`

AGENTS.md 是整个 Wiki 的核心配置文件。它让 LLM 从通用聊天机器人变为专业的知识库维护者。用户和 LLM 在使用过程中共同演进这份文档，逐步发现适合自己领域的最佳实践。

```markdown
---
type: agents
---

本文档定义此 LLM Wiki 的结构约定和行为规范。LLM 在执行 ingest/query/lint 操作时必须遵循这些规则。用户和 LLM 共同维护此文档，随着知识库演进持续完善。

## 页面类型

| 类型 | 标题前缀 | 存放目录 | 说明 |
|------|---------|---------|------|
| source | Source: | wiki/sources/ | 对 raw/ 素材的分析摘要 |
| entity | Entity: | wiki/entities/ | 人物、组织、工具、项目等 |
| concept | Concept: | wiki/concepts/ | 方法论、模式、理论等 |
| comparison | Comparison: | wiki/comparisons/ | 对比分析（通常由 query 产出） |
| overview | Overview: | wiki/overviews/ | 主题综述（通常由 query 产出） |

## 命名规范

- 标题前缀严格遵循上表
- Entity 以名词命名，Concept 以主题命名
- Source 标题取原文标题，过长时适当缩写

## 引用规范

- 文档内所有对 raw 素材/其他页面的引用统一使用 `[[wikilink]]`（Obsidian 双向链接）
- 外部链接保留原始 URL（不受此限制）
- INDEX.md 页面注册表的「路径」列同样使用 vault 相对路径

## 工作流规则

- **ingest**: 用户将素材放入 raw/ 后通知 LLM → LLM 从 raw/ 读取内容 → 在 wiki/ 创建 Source 摘要和关联页面 → Source 页的「原始来源」用 `[[...]]` 引用 raw/ 下的素材
- **query**: 从 INDEX.md 定位相关页面 → Read 并综合回答 → 有价值的回答归档为 Overview/Comparison 回流到 wiki
- **lint**: 检查矛盾、过时声明、孤立页、缺失页面、断链、交叉引用缺失 → 生成报告 → 建议新问题和新源

## 领域约定

> 以下为默认配置，可根据使用习惯调整

- **提取粒度**: 精选（仅提取有充分信息支撑的实体/概念，≥3 条关键事实）
- **摄入模式**: 交互式（提取前展示预览并等待确认）
- **归档策略**: 推荐归档（对比分析和综述主动推荐，用户一键确认）
- **领域关键词**: {{用户填写，帮助 LLM 识别领域内的重要实体和概念}}

{{由用户和 LLM 在使用过程中逐步补充，例如：}}
{{- 本知识库聚焦的领域和范围}}
{{- 特定术语的翻译或命名约定}}
```

---

## INDEX.md 初始模板

**标题**: `INDEX`
**存放**: `wiki/`

```markdown
# INDEX

> LLM Wiki 索引 — 所有页面的注册表和导航入口。

## 目录配置

| 目录 | Path |
|------|------|
| root ({{WIKI_NAME}}) | {{PARENT_DIR}}/{{WIKI_NAME}} |
| raw | {{PARENT_DIR}}/{{WIKI_NAME}}/raw |
{{RAW_SUBDIRS}}
| wiki | {{PARENT_DIR}}/{{WIKI_NAME}}/wiki |
| wiki/sources | {{PARENT_DIR}}/{{WIKI_NAME}}/wiki/sources |
| wiki/entities | {{PARENT_DIR}}/{{WIKI_NAME}}/wiki/entities |
| wiki/concepts | {{PARENT_DIR}}/{{WIKI_NAME}}/wiki/concepts |
| wiki/comparisons | {{PARENT_DIR}}/{{WIKI_NAME}}/wiki/comparisons |
| wiki/overviews | {{PARENT_DIR}}/{{WIKI_NAME}}/wiki/overviews |

> `{{RAW_SUBDIRS}}` 在 init 时按用户确认的 raw/ 子目录列表展开，每行格式：`| raw/<子目录名> | <相对路径> |`。
> 默认子目录：papers, articles, repos, datasets, images, assets。用户可在 init 时增删改。
> **reference 模式**：`{{RAW_SUBDIRS}}` 留空，`raw` 行直接指向被引用原目录的相对路径，子目录不静态登记。

## Wiki 配置

| 键 | 值 |
|---|---|
| wiki_name | {{WIKI_NAME}} |
| storage_type | vault |
| parent_dir | {{PARENT_DIR}} |
| raw_mode | {{RAW_MODE}} |
| raw_source_path | {{RAW_SOURCE_PATH}} |
| 创建时间 | {{YYYY-MM-DD HH:mm}} |
| 最后更新 | {{YYYY-MM-DD HH:mm}} |
| 页面总数 | 0 |

> - `storage_type`：固定 `vault`（本地 Obsidian vault）
> - `raw_mode`：`create` / `reference` / `none`；reference 模式 `raw_source_path` 填原目录相对路径，其余模式填 `-`

## 页面注册表

| 标题 | 类型 | 路径 | 目录 | 最后更新 | 关联 | 别名 | 标签 | Raw | 出链 | 入链 | 证据数 | 摘要 |
|------|------|------|------|---------|------|------|------|-----|------|------|--------|------|
```

---

## LOG.md 初始模板

**标题**: `LOG`
**存放**: `wiki/`

```markdown
# 操作日志

最新操作在最下方。
```
