---
name: vault-wiki
version: 8.0.0
description: vault wiki 整理：对指定目录的叶子 md 去重后聚合成一篇 wiki，支持单目录与批量两种模式，并可将成果上传到乐享知识库获得 web URL。遵循 Karpathy LLM Wiki 模式。
author: Steven Liang
license: MIT
platforms:
  - macos
  - linux
disable-model-invocation: true
---

# vault wiki 整理（v8 — 统一版：单目录 wiki + 批量蒸馏 + 乐享分发）

> **v8 (2026-09-03)**：合并 `vault-wiki` v7 + `vault-batch-distiller`，新增乐享知识库上传环节。
> **v7 (2026-07-29)**：引入两步法（结构化分析 → wiki 生成）。
> **v6 (2026-07-25)**：回归 Karpathy 原始模式。

## 核心原则（不变）

| 概念 | 说明 |
|------|------|
| **compounding** | 知识随时间积累，不是每次重新推导 |
| **source fidelity** | 每个数字/日期/引用都必须能在源文件中找到 |
| **raw 不可修改** | 叶子 md 只读不写（回链追加是唯一例外） |
| **distill, not copy** | 从多源提炼重组，不要原样复制单源 |
| **0 死链** | 所有 `[[wikilink]]` 必须能跳到真实文件 |

## 触发词

| 场景 | 触发词 |
|------|--------|
| 单目录整理 | "整理这个目录的 wiki"、"生成 wiki 页面"、"整理 wiki" |
| 批量蒸馏 | "把 `{L1}` 下所有二级目录整理成笔记"、"批量蒸馏 vault"、"用 vault-wiki 处理 21_ai" |
| 上传到乐享 | "把整理好的 wiki 上传到乐享"、"分发到乐享知识库" |

## 两种模式（v8 新增）

v8 统一两种工作模式，根据输入自动选择：

| 模式 | 输入 | 输出 | 触发 |
|:--|:--|:--|:--|
| **single-wiki** | 1 个目录路径 | `$VAULT/目录-wiki.md` | "整理这个目录" |
| **batch-distill** | 1 个 L1 目录路径（含多个 L2 子目录） | `$VAULT/llmwiki/{L1}/{L2}-YYYY-MM-DD.md` × N | "把 21_ai 批量蒸馏" |

> 旧 `vault-batch-distiller` skill 已废弃，所有功能并入本 skill 的 batch-distill 模式。

## Wiki 输出格式（Overview 模板）

```markdown
---
title: {主题标题}
type: wiki
stage: compiled
entity_type: overview
confidence: high
tags:
  - {标签1}
  - {标签2}
created: {YYYY-MM-DD}
updated: {YYYY-MM-DD}
sources:
  - "[[目录/文章A.md]]"
  - "[[目录/文章B.md]]"
  - ...（所有参与 wiki 的源文章，wikilink 格式）
# v8 新增：乐享知识库分发结果
lexiang_url: "https://lexiangla.com/pages/{entry_id}?company_from={company_code}"  # 成功时
lexiang_uploaded: 2026-09-03
# lexiang_status: waf_blocked  # 失败时（waf_blocked / empty / skipped）
---

# {主题标题}

> {一句话 tagline，可从源文章摘要提炼。}

## Overview

{一段话概括整个领域的核心价值、边界和当前状态。不是列表。}

## {正文章节1}

{从多个源中提炼重组，不要原样复制单个源。}

> 来源：[[目录/文章X.md]]

## {正文章节2}

{...}

> 来源：[[目录/文章Y.md]]

## ...（正文按主题组织，6-10 个章节）

## 延伸阅读

### 主题分类
- [[目录/文章A]] — {一句话说明}
- [[目录/文章B]] — {一句话说明}
```

### 格式规范

| 字段 | 规范 |
|------|------|
| **entity_type** | 固定写 `overview`（覆盖领域总览，包含定义/图谱/现状/挑战/缺口/延伸阅读） |
| **frontmatter sources** | 列出所有参与 wiki 的源文章 wikilink，正文不重复列出完整列表 |
| **正文来源标注** | 每节末尾一行 `> 来源：[[...]]`，涉及多篇写多行 |
| **Overview** | 一段话，不是列表，用来说明"这个领域是什么、核心价值、边界在哪" |
| **章节结构** | 按主题（theme）而非按文章组织，每章从多源提炼，蒸馏重组 |
| **Wikilink 格式** | `[[21_ai/openclaw/文件名.md]]`（vault 根目录相对路径） |
| **证据等级（v8 新增）** | 每个核心观点标注 🟢高 / 🟡中 / 🔴营销或待验证 |
| **lexiang_url（v8 新增）** | 上传乐享成功后写入；失败则写 lexiang_status |

## 关键规则

1. **不改原文**：源文件只读，wiki 笔记只写到 `目录-wiki.md` 或 `llmwiki/`
2. **0 死链**：所有 `[[文件名]]` 必须可跳转（用 `validate_links.py` 强制校验）
3. **分片**：单目录 >30 md 必须分批蒸馏
4. **证据等级**：每条核心观点标注 🟢/🟡/🔴
5. **skip 目录**：产物目录（如 `WorkBuddy-知识框架`、`llmwiki`）、空目录、`.trash` 等

## 工作流（6 步）

### Step 0 — 自动去重

1. 枚举叶子 md
2. 去掉 `_2` 后缀 + emoji 前缀
3. 同基础名保留最大文件，删除其余
4. 含"副本"的文件也删除

### Step 1 — 结构化分析

**读完全部叶子 md 后，先分析再写 wiki**：

#### 1a. 建立文章清单

| 序号 | 文件名 | 大小 | 核心主题 | 增量价值 |
|------|--------|------|---------|---------|
| 1 | xxx.md | 23KB | OpenClaw 架构 | 核心参考 |
| 2 | xxx_2.md | 5KB | 同上 | ❌ 与第1篇重复 |

对每篇叶子：
- 读 frontmatter（标题、日期、summary）
- 读正文前 20 行（H2 标题列表）
- 记录：主题、字数、是否与其他篇重复

#### 1b. 分类处理

| 分类 | 处理方式 |
|------|---------|
| **核心参考** | 全文读入，整合进 wiki 正文 |
| **重复变体** | 标注关联到核心篇，不重复写内容 |
| **空壳/无实质内容** | 写入 wiki 末尾的「收录说明」，正文不引用 |
| **Off-topic** | 写入「收录说明」，正文不引用 |

#### 1c. 确定章节结构

根据文章主题分布，规划 6-10 个章节，例如：

| 章节 | 对应主题 | 覆盖文章 |
|------|---------|---------|
| 核心概念图谱 | 产品定位/核心机制 | 核心篇 |
| 架构/记忆体系 | 技术架构/记忆方案 | 核心篇 |
| 工具协同 | Skills/ClawHub/工具链 | 扩展篇 |
| 实践方案 | 工作流/最佳实践 | 实践篇 |
| 挑战与局限 | 已知问题/边界 | 各篇综合 |
| 延伸阅读 | 按主题分类的完整源列表 | 全部 |

### Step 2 — Wiki 生成（两步法核心）

#### 2a. 先写 Overview（第一段）

根据所有文章提炼一段话，覆盖：
- 这个领域/主题是什么
- 核心价值主张
- 当前状态或发展阶段
- Wiki 涵盖的边界

#### 2b. 再按章节生成正文

每节写作规范：
- **蒸馏**：从多篇源文中提炼核心观点，重组而非摘录
- **结构**：每节围绕一个主题，包含定义/机制/案例/对比
- **标注**：节末用 `> 来源：[[...]]` 标注引用来源
- **事实精度**：数字/日期必须与原文一致，不确定时模糊表达
- **证据等级**：每个核心观点标注 🟢/🟡/🔴

#### 2c. 延伸阅读（按主题分组）

不是简单列表，而是按主题归类：
```
### 架构与机制
- [[文章A]] — 核心架构说明
- [[文章B]] — 技术细节

### 工具与生态
- [[文章C]] — 工具链全景
```

### Step 3 — 写入与校验

- **single-wiki 模式**：写到 `$VAULT/{目录}-wiki.md`（平级）
- **batch-distill 模式**：写到 `$VAULT/llmwiki/{L1}/{L2}-YYYY-MM-DD.md`

写完后**必须**运行 `validate_links.py` 校验：
```bash
python3 scripts/validate_links.py \
  --note "$VAULT/目录-wiki.md" \
  --src "$VAULT/目录"
```

修复死链直到 0。**0 死链是完成标志**。

### Step 4 — 回链（可选，默认开启）

每个叶子末尾追加（仅追加，不修改已有关联块）：

```markdown
---

## 关联 wiki

本文收录于 [[目录-wiki]]
```

> **注意**：回链只能追加，不能覆盖。如果叶子已有"关联 wiki"块则跳过。

### Step 5 — 乐享知识库上传（v8 新增，可跳过）

将整理好的 wiki 笔记**原文**上传到用户的乐享知识库，获得**真实可访问的 web URL**。

#### 5a. 何时跳过

- 用户明确说"不上传"
- wiki 是空壳/草稿，未完成
- 没有 `LEXIANG_TOKEN` 配置（检查顺序）：
  1. `~/.agents/skills/archive/lexiang-mcp-skill/mcp.json`
  2. `~/.mcporter/mcporter.json`
  3. 当前 dsh 的 `mcp.json`

#### 5b. 执行流程

1. **确认目标位置**
   - 默认上传到用户**个人知识库**的 `{L1}` 文件夹
   - 用户指定 URL/space_id 时优先使用
   - 没有个人知识库时，先 `whoami()` 确认

2. **创建文件夹**（首次上传某个 L1 目录时）
   ```python
   entry_create_entry(
     space_id: <personal_space_id>,
     parent_entry_id: <root_entry_id>,
     entry_type: "folder",
     name: "<L1>"  # 如 "21_ai"
   )
   ```

3. **逐个上传**（并行度 3-5，带 0.6s 间隔避免 WAF）
   ```python
   entry_import_content(
     space_id: <space_id>,
     parent_id: <folder_id>,
     name: "<wiki_file_name>.md",
     content_type: "markdown",
     content: <wiki_file 内容>
   )
   ```

4. **收集 entry_id，生成 URL 表格**
   - URL 格式: `https://lexiangla.com/pages/{entry_id}?company_from={company_code}`
   - 顶级域名需追加 `?company_from=` 参数
   - 三级域名（如 `csig.lexiangla.com`）直接用

5. **错误处理**
   - **WAF 拦截**：标记为 `⚠️ 需手动上传`，不重试
   - **content empty**：跳过，该 wiki 实际为空
   - **token 过期（401）**：引导用户到 `https://lexiangla.com/mcp` 续期
   - **rate limit**：自动 sleep 5-10s 重试

6. **写回到 wiki frontmatter**
   ```yaml
   lexiang_url: "https://lexiangla.com/pages/{entry_id}?company_from=..."  # 成功
   lexiang_uploaded: 2026-09-03
   # lexiang_status: waf_blocked  # 失败时
   ```

#### 5c. 乐享上传脚本

参考 `scripts/upload_to_lexiang.py`（v8 新增）。用法：

```bash
python3 scripts/upload_to_lexiang.py \
  --vault "$VAULT" \
  --note "$VAULT/21_ai/agent/AI-Agent知识库（蒸馏版）.md" \
  --l1 "21_ai_agent"
```

#### 5d. 输出结构

```
uploaded/
├── lexiang_uploads.json   # 完整 entry_id 映射
├── lexiang_failures.json  # 失败项 + 原因
└── upload_log.txt         # 完整日志
```

#### 5e. 乐享 vs Obsidian

两套体系并存互补：
- **Obsidian wikilink** `[[文件名]]`：本地 vault 跳转，仅自己可见
- **乐享 URL** `https://lexiangla.com/pages/{entry_id}`：公司 SSO 访问，可分享

### Step 6 — 收录说明

如果存在空壳/重复/off-topic 文章，在 wiki 末尾追加：

```markdown
## 收录说明

本 wiki 基于 `目录/` 下 N 篇文章整理。另有以下文章未纳入正文，原因如下：

**空壳/无实质内容（X篇）**：
- `文件名.md` — （原因）

**与已引用文章重复（X篇）**：
- `文件名A.md` ↔ `文件名B.md`

**弱相关（X篇）**：
- `文件名.md` — （原因）
```

## 批处理策略（batch-distill 模式专用）

| 单目录 md 数 | 处理方式 |
|-------------|---------|
| ≤ 30 | 一次蒸馏 |
| 31–100 | 分 2–3 批，每批 ≤30，先生成子摘要，再综合 |
| > 100 | 先聚类/分片，再分批综合 |

多个 L1 目录可启动 **并行后台 agent**；同一 L1 目录下的 L2 子目录顺序处理。

每个 L1 目录下创建 `.__progress.md`：
```markdown
- [YYYY-MM-DD HH:MM] 完成 {L2 主题}（X md）→ {输出文件名}
```

全部完成后生成或更新总索引：`llmwiki/!INDEX-YYYY-MM-DD.md`。

## 增量行为

- **首次运行**：生成完整 wiki
- **后续运行**：对比现有 wiki 的 sources，更新 `updated` 日期
- **有新叶子**：追加章节，更新 sources 和 updated
- **内容矛盾**：保留旧内容，追加 `> **Status: Disputed**` 块
- **已上传乐享**：检测 frontmatter 的 `lexiang_url`，跳过重复上传；失败的可以重试

## 命名规则

| 源目录 | Wiki 页面 |
|--------|----------|
| `21_ai/agent/` | `21_ai/agent-wiki.md` |
| `13_资讯/经济/` | `13_资讯/经济-wiki.md` |
| 批量模式 | `llmwiki/21_ai/agent-2026-09-03.md` |

## 资源

### 内置脚本

| 脚本 | 用途 |
|------|------|
| `scripts/dedupe.sh` | Step 0：去重叶子 md |
| `scripts/list_leaf_docs.sh` | 列出所有叶子 md |
| `scripts/list_source_docs.sh` | 列出源文档（用于回链） |
| `scripts/extract_md.py` | 提取标题层级 + 开头摘要（避免爆上下文） |
| `scripts/validate_links.py` | 校验 wikilink 0 死链 |
| `scripts/backlink.sh` | Step 4：批量追加"关联 wiki"回链 |
| `scripts/upload_to_drive.sh` | （旧）上传到 Google Drive（已废弃） |
| `scripts/upload_to_lexiang.py` | **v8 新增**：上传到乐享知识库 |

### 参考文档

| 文档 | 用途 |
|------|------|
| `references/wiki-schema.md` | wiki 页面字段规范 |
| `references/workflows/ingest.md` | 叶子入库流程 |
| `references/workflows/digest.md` | 批量蒸馏流程 |
| `references/workflows/query.md` | 基于 wiki 问答 |
| `references/workflows/lint.md` | wiki 质量检查 |
| `references/templates/pages.md` | wiki 页面模板 |
| `references/templates/init.md` | 初始化模板 |
| `references/prompt-template.md` | **v8 新增**：后台 agent prompt 模板 |
| `references/lexiang-setup.md` | **v8 新增**：乐享 MCP 配置说明 |

## 注意事项

1. **先分析后写**：Step1 结构化分析是 Step2 Wiki 生成的必要前提，不可跳过
2. **不要原样复制**：蒸馏重组，从多源提炼，不要复制原文
3. **Source fidelity**：每个事实必须能找到来源
4. **不递归**：只看目录直接子项，不进子目录
5. **Wikilink 跳转**：确保链接路径正确，能在 Obsidian 中正常跳转
6. **乐享 vs Obsidian**：乐享 URL 是公司 SSO 内访问；Obsidian wikilink 是本地跳转——两套体系并存互补
7. **WAF 注意**：乐享对部分内容敏感（特定字符/格式），上传失败时标记后人工处理

## 版本演进

| 版本 | 日期 | 变化 |
|:--|:--|:--|
| v6 | 2026-07-25 | 回归 Karpathy 模式，简化为一目录一 wiki |
| v7 | 2026-07-29 | 引入两步法（结构化分析 → wiki 生成） |
| **v8** | **2026-09-03** | **合并 batch-distiller + 新增乐享知识库上传** |

## Changelog (v8 详细)

**新增**：
- `batch-distill` 模式（统一单目录 + 批量）
- Step 5 乐享知识库上传环节
- 证据等级 🟢/🟡/🔴
- `references/lexiang-setup.md`（乐享 MCP 配置）
- `references/prompt-template.md`（后台 agent 模板，从 vault-batch-distiller 迁移）
- `scripts/upload_to_lexiang.py`（乐享批量上传）

**废弃**：
- 独立 skill `vault-batch-distiller`（功能全部并入 vault-wiki 的 batch-distill 模式）

**保留**：
- v7 的两步法骨架
- v7 的 Overview 模板
- v7 的回链机制
- v7 的所有 references/workflows
