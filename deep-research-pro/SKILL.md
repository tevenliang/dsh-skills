---
name: deep-research-pro
version: 3.0.0-codex
description: Multi-source deep research agent for Codex. Searches via
  tencent-yuanbao-search (国内) + tavily-search (海外)，抓取全文，合成调研报告。
homepage: https://github.com/paragshah/deep-research-pro
metadata:
  category: research
disable-model-invocation: true
---

# Deep Research Pro — Codex 适配版 v3

多源深度调研 skill。基于原版 `paragshah/deep-research-pro`，**Codex 适配版**：
- 国内内容 → `tencent-yuanbao-search`（腾讯元宝，中文一手）
- 海外/英文内容 → `tavily-search`（深度调研）
- 全文抓取 → `curl`
- 输出 → `~/Documents/steven_vault/02_work_notes/report/<slug>/`

## 何时使用

用户需要对一个主题做**多源、深度、有引用**的调研时使用，例如：
- 行业研究、市场分析
- 技术方案对比
- 学术/政策调研
- 决策支持（投资、采购、招聘）
- 任何"我要一个完整答案 + 来源"的请求

## 搜索工具组合

| 场景 | 用哪个 | 说明 |
|------|--------|------|
| **国内/中文信息** | tencent-yuanbao-search | 腾讯元宝，中文摘要干净直接 |
| **海外/英文一手来源** | tavily-search | 支持 `--depth advanced`，学术优先 |
| 混合主题 | 两者都用 | 国内部分用元宝，海外部分用 tavily |

## 工具链（Codex 适配）

| 步骤 | 工具 |
|------|------|
| 国内搜索 | `python3 ~/.agents/skills/Search/tencent-yuanbao-search/scripts/websearch.py --query="..."` |
| 海外搜索 | `python3 ~/.agents/skills/Search/tavily-search/scripts/tavily_search.py "..." --depth advanced --max-results 8` |
| 全文抓取 | `curl -sL <url> \| python3 -c '...'`（提取正文） |
| 输出目录 | `~/Documents/steven_vault/02_work_notes/report/<slug>/`（自动 mkdir -p） |

## 工作流程

### Step 1：理解目标（30 秒）

先问 1-2 个澄清问题：
- "你的目标是学习、决策、还是写东西？"
- "有特定角度或深度要求吗？"

用户说"直接调研"则跳过，按默认进行。

### Step 2：拆解子问题

把主题拆成 3-5 个子问题。每个子问题对应 1-2 次搜索。

**原则：国内话题用元宝，海外/英文话题用 tavily。**

例：主题"Similarweb 在中国市场的竞争情况"
1. Similarweb 国内客户与营收 → **元宝**
2. 国内网站流量分析竞品 → **元宝**
3. Similarweb vs Sensor Tower 竞品对比 → **tavily**
4. 出海企业用什么工具 → **元宝 + tavily**

### Step 3：多源搜索（核心）

**国内搜索（元宝）**：

```bash
python3 ~/.agents/skills/Search/tencent-yuanbao-search/scripts/websearch.py \
  --query="Similarweb 中国客户 出海企业" --freshness='year'
```

**海外搜索（tavily）**：

```bash
python3 ~/.agents/skills/Search/tavily-search/scripts/tavily_search.py \
  "Similarweb competitors Sensor Tower market share" \
  --depth advanced --max-results 8
```

**搜索策略**：
- 每个子问题用 2-3 个关键词变体
- 优先近 12 个月来源
- 总目标 15-30 个独立来源
- 优先级：官方 / 权威媒体 > 行业报告 > 博客 / 论坛

### Step 4：深度读取关键来源

对最有价值的 URL，用 curl 拉全文：

```bash
curl -sL "<url>" | python3 -c "
import sys, re
html = sys.stdin.read()
text = re.sub('<[^>]+>', ' ', html)
text = re.sub(r'\s+', ' ', text).strip()
print(text[:5000])
"
```

读 3-5 个关键来源全文。不只看搜索摘要。

### Step 5：综合 + 写报告

报告结构：

```markdown
# [主题]: Deep Research Report
*Generated: [date] | Sources: [N] | Confidence: [High/Medium/Low]*

## Executive Summary
[3-5 句核心结论]

## 1. [第一个主题]
[结论 + 行内引用]
- 要点 ([Source Name](url))
- 数据支撑 ([Source Name](url))

## 2. [第二个主题]
...

## 3. [第三个主题]
...

## Key Takeaways
- [行动建议 1]
- [行动建议 2]
- [行动建议 3]

## Sources
1. [Title](url) — [一句话说明]
2. ...

## Methodology
国内搜索 N 个 query（元宝），海外搜索 M 个 query（tavily），分析 X 个来源。
子问题：[list]
```

### Step 6：保存 + 交付

```bash
mkdir -p ~/Documents/steven_vault/02_work_notes/report/<slug>
```

报告保存到 `~/Documents/steven_vault/02_work_notes/report/<slug>/report.md`。

交付策略：
- **短报告**：直接在对话中贴全文
- **长报告**：贴摘要 + key takeaways，提示用户可查看完整文件

## 质量规则

1. **每条结论都要有引用**。不写无源论断。
2. **交叉验证**。只有一个来源说 → 标注"未独立核实"。
3. **时效优先**。优先近 12 个月来源。
4. **承认盲区**。找不到就说"信息不足"。
5. **不臆造**。不知道就说"insufficient data"。

## 示例触发

```
"研究核聚变能源的现状"
"Rust vs Go 后端服务对比"
"调研 2026 年 SaaS 创业的最佳策略"
"Similarweb 在国内市场的竞争情况"
```

## 依赖

- `tencent-yuanbao-search` skill（已配 key：`TENCENTCLOUD_WSA_APIKEY`）
- `tavily-search` skill（API Key：`TAVILY_API_KEY`）
- `curl` / `python3`（系统自带）

## 搜索 skill 协作矩阵

| 场景 | 推荐工具 |
|------|---------|
| 国内政策 / 行业报告 / 中文新闻 | **tencent-yuanbao-search** |
| 出海 / 跨境 / 中英混合主题 | **tencent-yuanbao-search + tavily 组合** |
| 英文学术 / 深度国际调研 | **tavily-search --depth advanced** |
| 快速事实核查（国内） | tencent-yuanbao-search |
| 快速事实核查（海外） | tavily-search（默认 depth） |
