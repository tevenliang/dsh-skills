# Page Templates — 页面与日志条目模板（vault 版）

操作运行时用于创建 wiki 页面和追加日志条目的模板。模板中 `{{...}}` 为占位符。引用统一使用 `[[wikilink]]`（vault 相对路径），不使用飞书 `<cite>` / `<source>`。

> 页面类型定义: [wiki-schema.md](../wiki-schema.md)

---

## Source 摘要模板

**标题**: `Source: {{原始标题}}`
**存放**: `wiki/sources/`

```markdown
---
type: source
created: {{YYYY-MM-DD HH:mm}}
updated: {{YYYY-MM-DD HH:mm}}
source: "[[{{RAW_PATH}}]]"
related: [{{关联页面 wikilink 列表}}]
aliases: [{{别名}}]
tags: [{{标签}}]
---

## 摘要

{{3-5 句话概括核心观点}}

## 关键要点

- {{要点 1}}
- {{要点 2}}
- {{要点 3}}

## 提取的实体

- [[{{entity 页面路径}}]] — {{角色}}

## 提取的概念

- [[{{concept 页面路径}}]] — {{体现}}

## 原始来源

- [[{{RAW_PATH}}]]
```

---

## Entity / Concept / Comparison / Overview 模板

创建时文件放在对应 `wiki/<类型>/` 子目录（详见 [adapter/vault.md](../adapter/vault.md)）。完整模板内容参见 [wiki-schema.md](../wiki-schema.md) 中各页面类型的「必须段落」定义。

---

## 日志条目模板

### INIT

```markdown

---

### {{ISO_TIMESTAMP}} — INIT

**操作**: 初始化 LLM Wiki
**详情**:
- 创建目录树: {{WIKI_NAME}}/ → raw/, wiki/, wiki/sources|entities|concepts|comparisons|overviews/
- 创建 AGENTS.md
- 创建 INDEX.md
- 创建 LOG.md
```

### INGEST

```markdown

---

### {{ISO_TIMESTAMP}} — INGEST

**来源**: "{{源文档标题}}"
**操作**:
- 创建源摘要: [[{{source 页面路径}}]]
- {{创建/更新页面列表}}
- 更新索引（新增 {{N}} 个页面）
```

### QUERY

```markdown

---

### {{ISO_TIMESTAMP}} — QUERY

**问题**: "{{用户查询}}"
**参考页面**:
- [[{{参考页面路径}}]]
- {{其他参考页面}}
**归档**: {{[[{{归档页面路径}}]] 或 "无"}}
```

### LINT

```markdown

---

### {{ISO_TIMESTAMP}} — LINT

**范围**: {{检查范围，如"全量" 或 "抽样 N 页"}}
**发现**:
- ERROR: {{N}} 项
- WARNING: {{N}} 项
- INFO: {{N}} 项
- SUGGESTION: {{N}} 项
**修复**: {{已修复项列表 或 "无"}}
```

### IMPORT

```markdown

---

### {{ISO_TIMESTAMP}} — IMPORT

**素材**:
- 标题: "{{素材标题}}"
- 类型: {{Markdown 文档 | 本地附件 | 外部链接}}
- 原始来源: {{vault 路径 / 本地路径 / 原始 URL}}
**目标目录**: `{{raw/papers/ | raw/articles/ | raw/repos/ | raw/datasets/ | raw/images/ | raw/assets/}}`
**操作**: {{复制文件 | 移动文件 | 抓取并创建文档}}
**结果**: [[{{RAW_PATH}}]]
**后续**: {{立即执行 ingest | 跳过，待后续摄入}}
```

批量导入多个素材时，一条 LOG 汇总所有素材：

```markdown

---

### {{ISO_TIMESTAMP}} — IMPORT

**批量导入 {{N}} 个素材**:
- [[{{raw/articles/xxx.md}}]] → `raw/articles/`（外部链接）
- [[{{raw/papers/yyy.pdf}}]] → `raw/papers/`（本地附件）
**后续**: {{立即执行 ingest | 跳过，待后续摄入}}
```

### DIGEST

```markdown

---

### {{ISO_TIMESTAMP}} — DIGEST

**源目录**: `{{源目录相对路径}}`
**摄入文章**: {{N}} 篇（新增 {{M}} 篇）
**输出**: [[{{聚合页路径}}]]
```
