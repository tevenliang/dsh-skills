---
name: find-skills-combo
slug: find-skills-combo
displayName: Find Skills（场景驱动技能发现）
version: 1.13.0
description: 场景驱动+关键词双模式技能发现工具。当用户用自然语言描述场景/需求（如"我想做一个海报""帮我分析股票"），或明确说"安装技能/find
  skills/找个skill"时，自动从官方内置、本地已安装、skillhub.cn、GitHub、skills.sh 开放生态
  五层联合搜索并推荐最合适的技能，支持一键安装。也覆盖查询类触发词（如"X 这个 skill 是干嘛的""帮我查 X 这个 skill""skillhub
  上有没有 X"），已完全替代官方原 find-skills 插件。
agent_created: true
disable-model-invocation: true
---

# find-skills（场景技能匹配器）

## Overview

本技能用于**场景驱动的技能发现引擎**——用户用自然语言描述需求，系统自动理解意图，联合搜索并推荐最合适的技能。

**搜索源（v1.13）**：
- `skillhub` CLI（`~/.local/bin/skillhub`）→ 直连 skillhub.cn，**含 stars / installs / downloads**
- `npx skills find`（skills.sh）→ 开放生态，含 stars / installs
- GitHub 搜索 → 含 stars

**⚠️ 输出格式（v1.13 强制）**：**必须用表格统一输出**，不可平铺罗列。

---

## 核心流程

### Step 1：理解用户场景

1. **任务意图**：用户想做什么？
2. **领域标签**：属于哪个领域？
3. **搜索关键词**：中英文 + 品牌别名扩展

#### 品牌别名扩展（强制）

| 类别 | 示例 |
|---|---|
| 中文全称 | 什么值得买 |
| 中文简称/缩写 | 值得买、smzdm |
| 拼音/音译 | zhidemai、haina |
| 英文原名 | Zhidemai |

搜索时用 **OR 组合**，避免同名不同字漏掉。

---

### Step 2：四层联合搜索

#### 2.0 零层：System Available Skills

系统传给你的 `available skills` 列表（name + description）逐条字面匹配，命中即报告，零开销。

#### 2.1 官方内置技能

扫描 WorkBuddy 内置技能目录，与用户场景语义匹配。

#### 2.2 本地已安装技能

扫描 `~/.workbuddy/skills/` + `~/.agents/skills/`，三级兜底。

#### 2.3 skillhub.cn CLI（主要搜索源）

```bash
skillhub search <关键词> 2>/dev/null
```

**补充 stars/installs/downloads 数据**：

```bash
skillhub skill rankings --type all 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
ranks = data.get('rankings', {})
lookup = {}
for k, v in ranks.items():
    if isinstance(v, dict) and isinstance(v.get('skills'), list):
        for s in v['skills']:
            slug = s.get('slug', '')
            ns = s.get('namespace', {})
            handle = ns.get('handle', '') if isinstance(ns, dict) else ''
            lookup[slug] = {
                'stars': s.get('stars', 0),
                'installs': s.get('installs', 0),
                'downloads': s.get('downloads', 0),
                'namespace': handle
            }
# 从 stdin 读 search 结果中的 slug，逐行匹配输出
"
```

**匹配规则**：在 rankings 结果中按 slug 精确匹配，匹配到则补充 ⭐/📥/⬇️ 数据，未匹配到标注 ❓。

#### 2.4 skills.sh

```bash
npx skills find [query] 2>/dev/null
```

输出中已含 `X installs`，直接解析。

#### 2.5 GitHub

```bash
curl -s "https://api.github.com/search/repositories?q=<关键词>+skill+in:name,description&per_page=10&sort=stars"
```

含 `stargazers_count`。

---

### Step 3：智能排序

| 优先级 | 来源 |
|--------|------|
| 1 | 官方内置 |
| 2 | 本地已安装 |
| 3 | skillhub.cn（参考 score） |
| 4 | skills.sh（参考 installs） |
| 5 | GitHub（参考 stars） |

去重：同一 skill 保留最高优先级，合并数据。

---

### Step 4：输出（⚠️ 必须用表格）

**⚠️ 输出格式（v1.13 强制）**：必须用 Markdown 表格统一输出，**不可平铺罗列**。数据不可查标注 ❓。

```
🔍 为你找到 {N} 个相关技能（搜索范围：{说明}）：

| 技能 | 说明 | ⭐ Stars | 📥 Installs | ⬇️ Downloads | 来源 | 安装命令 |
|---|---|---|---|---|---|---|
| {slug} | {一句话说明} | {stars} | {installs} | {downloads} | skillhub.cn | `skillhub install {slug} --namespace {ns}` |
| {slug} | {一句话说明} | {stars} | {installs} | — | skills.sh | `npx skills add {repo}@{slug} -g -y` |
| {name} | {description} | {stars} | — | — | GitHub | `git clone {url}` |
| {技能名} | {匹配理由} | — | — | — | ✅ 本地已安装 | — |
```

**列说明**：
- ⭐ Stars：GitHub stars，无数据标 ❓
- 📥 Installs：安装数，无数据标 ❓
- ⬇️ Downloads：下载数，无数据标 ❓
- 来源：skillhub.cn / skills.sh / GitHub / ✅ 本地已安装

---

### Step 5：一键安装

#### 客户端检测

```bash
echo $__CFBundleIdentifier
```

| 客户端 | 目标目录 |
|--------|----------|
| codebuddy | `~/.codebuddy/skills/` |
| 其他/空（默认） | `~/.workbuddy/skills/` |

#### skillhub.cn

```bash
skillhub install <slug> --namespace <namespace>
```

#### skills.sh

```bash
npx skills add <owner/repo@slug> -g -y
```

#### GitHub

```bash
git clone https://github.com/<user>/<repo>.git "$TMPDIR/<name>"
cp -r "$TMPDIR/<name>" <target-skills-dir>/
```

---

## 版本迭代记录

| 版本 | 日期 | 更新内容摘要 |
|------|------|------------|
| v1.11 | 2026-08-17 | 搜索源从 lightmake.site 切换为 skillhub.cn CLI |
| v1.12 | 2026-08-17 | 输出结果强制附带 stars/installs/downloads 数据 |
| **v1.13** | **2026-08-17** | **输出格式强制改为表格**，不可平铺罗列 |
