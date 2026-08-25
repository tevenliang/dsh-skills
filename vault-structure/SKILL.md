---
name: vault-structure
version: 2.0.0
description: Obsidian vault md 文档结构化重构工具 — 分析标题层级、重构
  h1/h2/h3、重组章节结构。触发词：「重构文档」「整理标题」「优化结构」「结构化」「重整 md」。
author: Steven Liang
license: MIT
platforms:
  - macos
  - linux
disable-model-invocation: true
---

# vault-structure v2.0 — vault md 结构化重构

> **v2.0 (2026-07-19)**：从飞书 docx 后端迁移为本地 vault md 后端，去除 `lark-cli` 依赖。原 `feishu-structure`。

## 核心能力

接收一个 vault md 文件路径，LLM 分析其标题结构，生成重构方案（h1/h2/h3 调整、章节合并/拆分/重组），用户确认后批量执行变更（直接重写 md 标题行）。

```
用户提供 md 文件路径
  │
  ├─ Step 1: 解析（parse_blocks.py）
  │    python3 scripts/parse_blocks.py <md_file>
  │    → 提取所有标题行（#/##/###）及层级，输出结构树 + 问题
  │
  ├─ Step 2: LLM 分析
  │    识别结构问题（伪装段落/层级跳跃/缺失标题/标题过细/空段落）
  │
  ├─ Step 3: 展示重构方案（对比表）
  ├─ Step 4: 用户确认
  ├─ Step 5: 批量执行（直接重写 md 标题行）
  └─ Step 6: 日志记录（追加到 $VAULT/logs/structure-log.md）
```

## 双平台路径

vault 根目录读 `$VAULT` 环境变量，未设按平台回退：
- macOS: `~/Documents/steven_vault`
- Linux/VM: `/home/ubuntu/webdav/steven_vault`

## 触发方式

用户说「重构文档」「整理标题」「优化结构」「结构化」「重整 md」时触发。

**必须提供 md 文件路径**（通常在 `$VAULT/` 下，如 `00_inbox/xxx.md`）。如未提供，要求用户给出路径。

## 脚本化执行（daemon 调用，非交互）

除上面的交互式流程（Step 1–6，需用户确认）外，本 skill 提供**脚本入口** `scripts/restructure_file.py`，供 VM daemon 无人值守调用：

- **引擎**：`glm-4-flash`（zhipu 免费档）
- **凭证**：`~/.agents/credentials/ominicrawl/zhipu.json` 或环境变量 `ZHIPU_API_KEY`
- **流程**：读 md → 正文标题数 < `MIN_HEADINGS`(默认 2) 才处理 → glm 生成操作清单（convert / insert_before）→ `validate()` 标题质量闸门（H2+ 标题含句末标点 `。；：` 或 >50 字直接拒绝，且必须恰好 1 个 H1）→ 改写文件；**任一校验失败则不改写文件，绝不损坏正文**
- **调用方**：VM daemon 的 `scan_inbox.py`（先 structure 后 summary；结构失败被捕获，不阻塞总结）
- **幂等**：已满足标题阈值则跳过

> ⚠️ **本 skill 被 VM daemon 直接调用**。在 Mac 更新本 skill（尤其是 `scripts/restructure_file.py` 或本 SKILL.md）后，必须执行 `/vm-skills-push` skill 把 Mac skills 推送到 VM，否则 VM daemon 下个小时起仍用旧代码。

## Step 1 — 解析

```bash
python3 scripts/parse_blocks.py <md_file>   # 输出标题结构树 + 问题
```

解析本地 md 的 `#/##/###` 标题行，输出 Markdown 结构摘要（标题层级树 + 层级分布 + 检测到的问题）。

**实战经验**：网页转存的文档（如微信公众号转存）章节标题常写成普通段落（`01标题` 形式），识别这类"伪装成段落的标题"是核心能力之一。判断依据：纯数字开头 + 无句末标点 + 短文本（<50字）。

## Step 2 — LLM 分析

读取解析输出后，LLM 执行以下分析：

### 2.1 识别结构问题

| 问题类型 | 判断标准 | 建议操作 |
|---|---|---|
| **伪装段落** | 普通段落以纯数字开头（01/02/03）且无句末标点且<50字 | 转为标题（##） |
| **缺失标题** | 某段连续正文超过 3 个段落 | 建议插入 ##/### |
| **层级跳跃** | # 后直接 ###（无 ##） | 建议降级为 ## |
| **标题过细** | ### 后只有 1-2 段又 ### | 建议合并或升级 |
| **空段落** | 段落内容为空 | 删除 |
| **同义段** | 相邻同级标题内容不相关 | 需人工确认 |

### 2.2 重构方案生成

```
## 重构方案

| 行号 | 原级 | 原标题 | 操作 | 新级 |
|---|---|---|---|---|
```

**执行顺序**（重要）：
1. 先处理所有「删除标题行」
2. 再处理「插入新标题行」
3. 最后处理「调整级别」（改 # 数量）

## Step 3 — 展示方案

以 Markdown 表格展示，清晰对比变更前后。

## Step 4 — 用户确认

**必须等待用户确认后再执行。**

## Step 5 — 批量执行

直接重写 md 文件的标题行（用 Edit/str_replace 改对应行的 `#` 数量，或插入/删除标题行）。本地 md 无 block_id 失效问题，逐行改即可。

### 调整标题级别的方法

本地 md 的级别 = `#` 的数量：
```
## 章节标题   →  # 章节标题   （升级 h2→h1）
01 章节标题   →  ## 01 章节标题  （伪装段落→h2）
```

## Step 6 — 日志记录

追加到 `$VAULT/logs/structure-log.md`：

```markdown
## 2026-07-19 文档重构

- **文档**：`<md_file>`
- **变更**：
  - 调整级别：X 项
  - 新增标题：Y 项
  - 删除标题：Z 项
- **操作人**：vault-structure v2.0
```

## 适用场景

✅ **适合**：
- 网页转存的文档（微信公众号等）章节标题常写成普通段落，需结构化
- 文档标题层级混乱（#/##/### 乱跳）
- 文档缺少结构（长段正文无小标题）
- 从外部导入的 Markdown 文档结构不规整

❌ **不适合**：
- 纯内容修改（改文字内容）→ 用 str_replace
- 表格、图片等非文本内容重组
- 文档创建

## 注意事项

- 执行前建议用户确认方案，特别是涉及删除操作
- 本地 md 无 block_id 失效问题，逐行改标题即可
- 如果文档较长（标题 >50 行），建议分批展示方案

## 更新记录

- v1.0–v1.1：feishu-structure，走飞书 docx block fetch/update
- 2026-07-19：v2.0 迁移为本地 vault md 后端，去 lark-cli，解析脚本改读本地 md，目录归位 `skills/PRODUCTIVITY/vault-structure`
