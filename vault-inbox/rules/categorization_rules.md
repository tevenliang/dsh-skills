# vault-inbox 分类规则 v2.0

> 从 Steven 纠正中提炼，2026-07-15

---

## 核心分类原则

### 1. 标题有明确工具名的 → 归对应分类，不是大模型Llm

- **OpenCLI** → AI / Cli（不是大模型Llm）
- **MiniMax MMX CLI / mmx-cli** → AI / Cli
- **Harness Engineering** → AI / Coding编程（是coding工程领域）
- **Headroom** → AI / Skills（节省token的skill）
- **Pi编码智能体** → AI / Coding编程（极简编程工具）

### 2. 基金相关内容 → 投资理财/基金，不是股市行情

- 标题含"基金"、"养基"、"基金经理"等 → **投资理财Investment / 基金**
- 例外：纯市场宏观分析（央行抽水、纳指暴跌）→ 股市行情

### 3. 腾讯/大厂AI战略分析 → 大模型Llm 或 新闻资讯/企业，不是股市行情

- 腾讯AI战略、大厂AI布局分析 → **人工智能AI / 大模型Llm**
- 涉及具体企业新闻动态 → **新闻资讯/企业**

### 4. 应用工具类产品 → 应用工具/Apps

- **WPS** → 应用工具/Apps
- **Obsidian** → 应用工具/Apps（Obsidian本身是App，插件文章也归Apps）
- **Browser Harness** → 应用工具/浏览器（浏览器操作系统）

### 5. 生活/购物内容 → 家庭生活，不是投资理财

- "我们最近买的X个新玩意"、购物分享 → **家庭生活/其他**

### 6. 新闻资讯/企业 归类原则

- 大厂动态（腾讯、阿里、字节）、AI战略发布 → 新闻资讯/企业
- 注意：仅当文章核心是"企业动态/新闻"时归此类；若核心是"AI技术/大模型"→ 大模型Llm

---

## 关键词 → 分类速查表

| 关键词 | 分类 |
|--------|------|
| OpenCLI / MMX CLI / CLI | AI / Cli |
| Harness / Coding / Pi编码 | AI / Coding编程 |
| Headroom / Skill插件 | AI / Skills |
| 基金 / 养基 / 基金经理 | 投资理财/基金 |
| 腾讯AI / 大厂战略 / 企业AI布局 | AI / 大模型Llm |
| 大厂动态 / 企业新闻 / 汤道生 | 新闻资讯/企业 |
| WPS / Obsidian / App应用 | 应用工具/Apps |
| 购物 / 新玩意 / 家庭购物 | 家庭生活/其他 |

---

## 错误模式（易错点）

1. ❌ 看到"腾讯/AI"就归股市行情 → ✅ 读内容：战略分析→大模型Llm，新闻动态→新闻资讯/企业
2. ❌ 看到"OpenCLI"就归大模型Llm → ✅ OpenCLI = CLI工具 → AI/Cli
3. ❌ 基金简报归股市行情 → ✅ 基金内容 → 投资理财/基金
4. ❌ Obsidian插件归Skills → ✅ Obsidian本身是App → 应用工具/Apps

---

## 补充规则（2026-07-15）

### 核心原则：读标题工具名，不读内容

- **大多数分类靠标题关键词即可判断**，不需要读内容
- 只有标题模糊（如只写"深度解析"）时才读 doc 内容
- 避免过度分析导致分类过散

### 执行与日志规范

- 分类结果由 agent（LLM）结合本规则 + fewshots/ 决定后，交给 `vault_inbox.py apply` 执行 move
- 每次移动明细追加到 `$VAULT/logs/inbox-move-log.json`，不调用飞书 API
- 移动不可逆，apply 前务必确认结果 JSON 的 target 目录正确（只 move 到现有 vault 数字目录）
