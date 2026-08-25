---
name: vault-summary
version: 2.0.0
description: vault summarizer — 用主题-bullet 模式（得到大脑风格）把任意长内容（文章/视频/播客/转录/本地
  md）压成结构化总结 JSON，并把 `## 总结`（🎯一句话核心 / ⏳速读 / 💡核心金句）注入 md 的 abstract 区。对齐 crawl
  总结模块（同 prompt、同 JSON
  schema、同注入格式）。触发词：「总结」「总结一下」「帮我总结」「summarize」「梳理一下」「提炼」「文件总结」。
author: Steven Liang
license: MIT
platforms:
  - macos
  - linux
type: prompt+script
disable-model-invocation: true
---

# vault-summary v2.0 — vault 长内容蒸馏 + 文件总结

> ⚠️ **本 skill 被 VM daemon 直接调用**。在 Mac 更新本 skill（尤其是 `scripts/summarize_file.py` 或本 SKILL.md）后，必须执行 `/vm-skills-push` skill 把 Mac skills 推送到 VM，否则 VM daemon 下个小时起仍用旧代码。

## 定位

vault summarizer — 把长内容压成结构化总结 JSON 的引擎。**只负责总结本身，不负责落盘/抓取/分发**。

任何要"消化一段长内容"的需求，都调它。调用方拿到 JSON 后自行决定怎么用：
- 本地落盘：把 JSON 写入 Obsidian vault 对应目录的 md
- 对话回显：直接 echo 给用户看
- 其他 vault skill：作为上游总结模块被复用（如 vault-inbox 分类前先提炼要点）
- 未来的：邮件总结、播客总结、读书笔记等，同模式复用

## 输入

文本（任意长内容）：
- 文章正文 / 公众号 / 知乎回答 / 本地 md 文档全文
- B站/抖音/小红书 视频转录文本
- 播客转录
- 用户贴的链接（agent 自行抓取后传入）

## 输出（严格 JSON）

```json
{
  "summary": "一句话总结（≤80字）",
  "topics": [
    [["💹", "主题标题"], ["bullet1", "bullet2", "bullet3"]],
    [["📉", "主题标题"], ["bullet1", "bullet2"]]
  ]
}
```

每个 topic 结构：`[[emoji, title], [bullets]]`
- emoji: 按主题类型选（见下方 emoji 字典）
- title: 13字以内主题句
- bullets: 2-5 条，每条一个具体事实点

文件总结实际注入 md 的 `## 总结` 段（与 crawl 同款格式）：
```
## 总结

🎯 一句话核心：
<summary>

⏳ 速读
- <emoji> **<主题标题>**
  - <bullet1>
  - <bullet2>

💡 核心金句
- <原文金句>
```
> 注入位置：frontmatter 之后、第一个 `##` 之前（abstract 区），便于下游（vault-inbox / 抓取稿）直接读取。

## 核心规则（执行 prompt 全文见 `scripts/prompt_topics.md`）

1. **零格式噪声** — bullet 不带 [00%-25%] / "原文提到" / "作者认为" 等前缀
2. **覆盖度优先** — 数字/专有名词/对比/因果链全保留；不抽象成"市场存在风险"
3. **主题层级** — 拆 3-5 个主题板块（短文 3 个/长文 5 个），主题句 ≤13 字
4. **emoji 按主题类型选** — 不是装饰
5. **bullet 是完整事实点** — 原文一段连讲 4 个事实就拆 4 条
6. **不发明内容** — 只总结原文，不补充背景/不评价/不预测

## emoji 字典

| emoji | 场景 |
|---|---|
| 💹 金融/价格/交易 | 📈 上涨/增长/扩张 | 📉 下跌/风险/收缩 |
| 🔒 监管/约束/规则 | 🏛 政策/制度 | ⚖️ 法律/合规/对比 |
| 💡 核心观点/结论 | 🎯 行动/策略 | 🛠 方法/技巧 |
| ⚠️ 警告/警示 | 📊 数据/统计 | 🔍 观察/分析 |
| 🌐 国际/全球 | 🇨🇳🇺🇸🇰🇷🇯🇵 | 🏢 公司/企业 |
| 🤖 AI/技术/产品 | 📚 知识/教育 | 🧠 思维/方法论 |
| 📰 事件/新闻 | 🏠 国内/居住 | 🍔 生活/消费 |
| ❤️ 健康/情感 | 🚀 增长/突破 | ⚙️ 系统/架构 |

> 选最接近主题情绪/领域的一个，不要混用。

## 失败回退

脚本层（`summarize_file.py`）健壮性：
- `parse_json_strict` 容错抠 JSON（去 ``` 包裹 / 前后杂字）
- `normalize_topics` 修复嵌套过深/过浅的 topics 形状
- `validate` 强校验：summary 非空、topics ≥2 且 ≤5、主题标题 ≤13 字、bullets 非空
- 引擎链：glm（zhipu）失败 → bailian（`bl`）→ minimax（`mmx`），逐引擎重试；全失败报 `❌ 总结失败 (所有引擎)`

纯 prompt 调用（agent 贴 prompt_topics.md 时）建议回退：
1. JSON 解析失败 / 主题 < 2 / 标题超 14 字 → 立即重新生成一次
2. 再失败 → 退回"5-8 条平铺 bullet"模式
3. 还失败 → 报告"主题-bullet 失败，已用平铺兜底"

## 调用方

| 调用方 | 用法 |
|---|---|
| 本地落盘 | 拿到 JSON 后写入 Obsidian vault 对应 md（落盘逻辑由调用方实现） |
| 用户对话 | 直接 echo 给用户看 |
| 其他 vault skill | 作为上游总结模块复用（如 vault-inbox 分类前提炼要点） |
| 未来的：邮件总结、播客总结、读书笔记等 | 同模式复用 |

## 文件总结（summarize_file.py）

对齐 crawl 总结模块（`crawl/common-summary/summarize.py`）：读 md → 去 frontmatter → LLM 引擎链 → JSON 校验归一 → 把 `## 总结`（🎯/⏳/💡）注入 abstract 区。

```bash
# 对一篇 md 做文件总结（默认注入 ## 总结 段）
python3 ~/.agents/skills/PRODUCTIVITY/vault-summary/scripts/summarize_file.py /path/to/note.md

# 只输出 JSON、不写回文件
python3 .../summarize_file.py /path/to/note.md --no-inject

# 强制覆盖已有 ## 总结
python3 .../summarize_file.py /path/to/note.md --overwrite

# 指定引擎（默认 auto：glm 主, bailian / minimax 兜底）
python3 .../summarize_file.py /path/to/note.md --engine glm
```

- system prompt 取自 `scripts/prompt_topics.md` 的 `## Prompt` 段（单一真相源，与 agent 贴入的 prompt 完全一致）
- 引擎：`glm-4-flash`（zhipu 凭证 `~/.agents/credentials/ominicrawl/zhipu.json`）主，`bl` / `mmx` CLI 兜底
- 输出：stdout 打印 JSON；默认把 `## 总结` 注入 md 的 abstract 区（frontmatter 之后、第一个 `##` 之前）
- 依赖：Python 3.10+，凭证 + `bl`/`mmx` CLI（与 crawl 共用，无需额外安装）

## 与 crawl 总结模块的对齐

| 维度 | crawl `common-summary/summarize.py` | vault-summary `summarize_file.py` |
|---|---|---|
| prompt 真相源 | `summarize-expert/scripts/prompt_topics.md` | 本 skill `scripts/prompt_topics.md` |
| JSON schema | `{summary, topics}` | 同 |
| 引擎链 | glm → bailian → minimax | 同 |
| 注入格式 | `## 总结` + 🎯/⏳/💡 | 同（直接复用同款代码） |
| 落盘 | 写 crawl md 的 abstract 区 | 写 vault md 的 abstract 区 |

> vault-summary 不 import crawl 内部模块，仅对齐行为/格式，保持独立可维护。

## 文件结构

```
~/.agents/skills/PRODUCTIVITY/vault-summary/
├── SKILL.md                 ← 本文件
├── README.md
├── LICENSE
└── scripts/
    ├── prompt_topics.md     ← 完整 prompt 模板（## Prompt 段为系统提示真相源）
    └── summarize_file.py    ← 文件总结脚本（对齐 crawl 总结模块）
```

> v2.0 起不再是纯 prompt skill：新增 `summarize_file.py` 可直接对本地 md 做文件总结。
> 纯 prompt 模式仍可用——agent 直接贴 `prompt_topics.md` 的 `## Prompt` 段即可。

## 更新记录

- 2026-07-09：v1.0 从 `feishu-notes/scripts/prompt_topics.md` 抽出独立成 skill
- 原 v2.0（feishu-notes 内嵌版）核心规则已并入
- 2026-08-11：v2.0 新增 `scripts/summarize_file.py`，对齐 crawl 总结模块（同 prompt / 同 JSON schema / 同 `## 总结` 注入格式）；补 license/platforms；清理飞书系死链接
