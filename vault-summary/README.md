# vault-summary

> AI-powered universal content summarizer — topic-bullet mode (Get' brain style).
> Turn any long content (article, video transcript, podcast) into a structured JSON summary.

**Core**: "Input raw text → Output structured summary JSON" engine.
**Output format**: `H2 quick-scan outline → H3 topic headers → bullet lists`.
**No storage logic**: callers decide how to persist (Feishu / local / echo).

---

## Features

- **Topic-bullet structure** — 3–5 themed sections with emoji, each containing 2–5 factual bullets
- **Coverage-first** — every specific fact stays in the summary; no abstract vague statements
- **Zero format noise** — no time stamps, confidence scores, "the article mentions...", or guide prefixes
- **Language-aware** — output language follows the input language
- **Zero dependencies** — pure prompt skill, no external scripts required
- **Fallback strategy** — auto-retries on parse failure, degrades gracefully to flat-bullet mode

---

## Installation

### Codex Skill (recommended)

If you're using Codex, install to your skills directory:

```bash
git clone https://github.com/YOUR_USERNAME/vault-summary.git \
  ~/.agents/skills/PRODUCTIVITY/vault-summary
```

### Standalone

Copy `scripts/prompt_topics.md` into your pipeline. The skill is just a prompt template — no runtime dependencies.

---

## Usage

### As a Codex Agent

When the user says: 「总结」「帮我总结」「summarize」「梳理」「提炼」

1. Read the raw text (article / transcript / any long content)
2. Load `scripts/prompt_topics.md` and pass the prompt to your LLM
3. Parse the JSON response and return it to the caller

### As a Standalone Prompt

Paste `scripts/prompt_topics.md` into any LLM prompt tool. The output is always a strict JSON object.

### Output JSON Schema

```json
{
  "summary": "一句话总结（≤80字）",
  "topics": [
    [["💹", "主题标题"], ["bullet1", "bullet2", "bullet3"]],
    [["📉", "主题标题"], ["bullet1", "bullet2"]]
  ]
}
```

Rendered in Feishu:

```
📌 总结：...
## 速读大纲
### 💹 主题1
• bullet1
• bullet2
### 📉 主题2
• bullet1
```

---

## Core Rules

| Rule | Description |
|------|-------------|
| Zero noise | No timestamps, confidence scores, "原文提到...", guide prefixes |
| Coverage-first | Keep all numbers, proper nouns, comparisons, causal chains |
| Topic hierarchy | 3–5 themed sections; topic title ≤ 13 chars |
| Emoji = topic type | Not decoration; choose by domain/emotion |
| Bullets = facts | One fact per bullet; no abstract labels |
| No invention | Only summarize what's in the original text |

---

## Emoji Dictionary

| Emoji | Scenario |
|-------|----------|
| 💹 金融/价格/交易 | 📈 上涨/增长/扩张 | 📉 下跌/风险/收缩 |
| 🔒 监管/约束/规则 | 🏛 政策/制度 | ⚖️ 法律/合规/对比 |
| 💡 核心观点/结论 | 🎯 行动/策略 | 🛠 方法/技巧 |
| ⚠️ 警告/警示 | 📊 数据/统计 | 🔍 观察/分析 |
| 🌐 国际/全球 | 🏢 公司/企业 | 🤖 AI/技术/产品 |
| 📚 知识/教育 | 🧠 思维/方法论 | 📰 事件/新闻 |

---

## File Structure

```
vault-summary/
├── SKILL.md                 ← Codex skill definition (agent reads this)
├── scripts/
│   └── prompt_topics.md    ← Full prompt template (the core artifact)
├── README.md               ← This file
└── LICENSE                 ← MIT License
```

---

## Example Output

**Input**: Article about Korean central bank naming leveraged ETF pro-cyclical mechanisms.

```json
{
  "summary": "韩国央行点名杠杆ETF顺周期机制，预计将引发资金流出并提高购买门槛。",
  "topics": [
    [["💹", "韩国央行点名杠杆ETF顺周期机制"],
     ["韩国央行公开指出杠杆ETF存在顺周期机制问题",
      "该机制会放大市场波动、加剧市场集中、影响企业发展、强化单边资金流",
      "央行表态预计将导致韩国杠杆ETF资金流出",
      "监管可能给购买者加上更多约束条件"]],
    [["📉", "韩国市场杠杆投资风险"],
     ["韩国投资风格'一窝风'、'猛战'，喜欢火上浇油",
      "杠杆既放大收益，也同等放大风险",
      "此时加杠杆可能直接走到'愚昧之巅'"]],
    [["🔒", "提高杠杆ETF购买门槛的正面影响"],
     ["监管增加购买门槛，有助于延长市场趋势的持续时间",
      "此举被认为是积极举措，有助市场健康发展"]]
  ]
}
```

---

## Callers

This skill is designed to be called by other skills:

| Caller | How it uses the output |
|--------|----------------------|
| feishu-notes | Writes JSON topics into Feishu docx via `feishu_io.py` |
| subscription-crawl | Embeds JSON in LLM summary card, publishes to Feishu wiki |
| link-crawl | Calls summarize after fetching a single URL |
| User chat | Echoes JSON directly to user |

---

## Author

Steven Liang — 2026

---

## License

MIT — see [LICENSE](LICENSE).
