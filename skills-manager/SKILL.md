---
name: skills-manager
description: 管理 ~/.agents/skills/ 仓库的本地 skills — 分类、新增、移动、归档、删除。当用户提到「把 xxx
  skill 放到 xxx」「新建一个 skill」「归档 xxx」「分类」「管理 skills」「整理 skills」时使用。本 skill 是
  skills 仓库的唯一入口规范，所有新增/移动/归档/删除操作前必须先查本 skill 确认分类。
disable-model-invocation: true
---

# skills-manager

本 skill 是 `~/.agents/skills/` 仓库的元数据 / 入口规范。
**任何新增 / 移动 / 归档 / 删除 skill 的操作前，agent 必须先查本 skill 确认分类。**

## 1. 当前分类结构（2026-08-17 更新）

```
~/.agents/
├── skills/                        # ✅ git 管理的主仓库
│   ├── .system/                  # Codex 系统内置（gitignored）
│   ├── APPS/                     # 应用程序类
│   ├── CLI/                      # CLI 工具 wrapper
│   ├── DEVELOPER/                 # 开发辅助
│   ├── Finance/                  # 金融数据
│   ├── PPT/                       # PPT 相关
│   ├── PRODUCTIVITY/              # 生产力工具
│   ├── Search/                   # 搜索/研究
│   ├── System/                   # 系统管理
│   ├── common/                    # 公共模块
│   └── crawl/                     # 多平台内容抓取套件
│
└── archived_skills/              # ❌ 已归档（不在 skills 目录）
    ├── ominocrawl/               # 旧版爬虫
    ├── metaso-search-skill/       # 秘塔搜索
    └── ...（30+ 其他归档）
```

### 各分类详情

| 分类 | 数量 | 成员 |
|------|------|------|
| `.system/` | 6 | imagegen, openai-docs, plugin-creator, skill-creator, skill-installer, review-agent（gitignored，不入库） |
| `APPS/` | 5 | grill-me, grilling, interview-expert, notebooklm, pretty-mermaid |
| `CLI/` | 14 | bailian-cli, bailian-finetune, bailian-gen, bailian-managed-agent, bailian-protocol, github, groq-cli, himalaya, kdocs, lark-cli, mmx-cli, obsidian-cli, ocx-cli, opencli, xhs-cli |
| `DEVELOPER/` | 1 | code-review |
| `Finance/` | 5 | akshare-query, fund-portfolio-visualizer, mx-finance-data, neodata-financial-search, yingmi-skill |
| `PPT/` | 2 | dashi-ppt, huashu-design-full |
| `PRODUCTIVITY/` | 12 | Apple Task Review, apple-notes, customer-manager, daily-review, material-organizer, password-manager, vault-batch-distiller, vault-inbox, vault-ocr, vault-structure, vault-summary, vault-wiki, wechat-invoice |
| `Search/` | 16 | aihot, anysearch, deep-research-pro, find-skills-combo, haina-shopping-assistant, metaso-search-skill, neodata-financial-search, openrouter-hot-model-router, price-compare, search-orchestrator, tavily-search, tencent-news, tencent-yuanbao-search, tianji-search, web-access, web-search-exa, wechat-article-search |
| `System/` | 4 | handoff, skills-manager, usage-check, vm-skills-push |
| `crawl/` | 1 | ominicrawl-crawl（多平台抓取套件，含 common-*, ingest-*） |
| `common/` | - | agent_platform.py, py.sh（公共模块） |

---

## 2. 分类决策树

拿到一个 skill（或一个待新建 skill），按以下顺序判断：

```
Q1. 是 Codex 系统内置吗？（imagegen / openai-docs / skill-* / plugin-*）
    → YES: 放到 .system/（gitignored，不入库）
    → NO:  Q2

Q2. 是已废弃/被取代的 skill 吗？
    → YES: 移到 ~/.agents/archived_skills/
    → NO:  Q3

Q3. 是某个 CLI 工具的 wrapper 吗？（gh / bl / opencli / kdocs 等）
    → YES: 放到 CLI/
    → NO:  Q4

Q4. 是 macOS 原生应用或第三方 app 封装吗？（备忘录 / 日历 / 微信 / notebooklm 等）
    → YES: 放到 APPS/
    → NO:  Q5

Q5. 是开发辅助工具吗？（code-review 等）
    → YES: 放到 DEVELOPER/
    → NO:  Q6

Q6. 是金融数据/投资分析吗？（AKShare / 基金 / 行情等）
    → YES: 放到 Finance/
    → NO:  Q7

Q7. 是 PPT 相关吗？
    → YES: 放到 PPT/
    → NO:  Q8

Q8. 是个人生产力工具吗？（笔记 / 复盘 / 客户 / 密码 / 总结等）
    → YES: 放到 PRODUCTIVITY/
    → NO:  Q9

Q9. 是联网搜索/信息检索吗？（tavily / tencent-yuanbao 等）
    → YES: 放到 Search/
    → NO:  Q10

Q10. 是系统管理工具吗？（VM 控制 / API 用量 / skills 管理等）
    → YES: 放到 System/
    → NO:  Q11

Q11. 是自包含的复杂项目（带 pipeline / config / 独立文档体系）吗？
    → YES: 放到 crawl/（如果是抓取相关）或根目录
    → NO:  询问用户
```

---

## 3. 命名规范

| 位置 | 规范 | 示例 |
|---|---|---|
| `.system/` | Codex 内置规范 | imagegen / openai-docs |
| `APPS/` | 简短英文 | apple-notes / notebooklm |
| `CLI/` | CLI 工具名 | github / opencli / bailian-cli |
| `DEVELOPER/` | 简短英文 | code-review |
| `Finance/` | 英文连字符 | akshare-query / yingmi-skill |
| `PPT/` | 英文连字符 | dashi-ppt |
| `PRODUCTIVITY/` | 英文连字符 | vault-notes / daily-review |
| `Search/` | 英文连字符 | tavily-search / web-access |
| `System/` | 英文连字符 | vm-control / skills-manager |
| `crawl/` | 统一抓取套件 | common-*, ingest-* |

---

## 4. 标准操作流程

### 4.1 新增 skill
```
1. 查分类决策树确认目标分类
2. 跟用户确认目标分类
3. 安装/创建 skill
4. git add + commit
```

### 4.2 移动 skill
```
1. 检查目标分类是否合理
2. 执行移动
3. git add + commit
```

### 4.3 归档 skill
```
1. mv skill ~/.agents/archived_skills/
2. git add + commit
```

### 4.4 删除 skill（彻底删除）
```
1. 用户确认
2. rm -rf skill/
3. git add + commit
```

---

## 5. 重要约定

1. **skills 主仓库在 `~/.agents/skills/`**，有独立 git
2. **归档 skills 在 `~/.agents/archived_skills/`**，不在 skills 目录
3. **crawl/** 是多平台内容抓取套件，不是普通 skill
4. **common/** 是公共模块，不是 skill
5. **HANDOFF-*.md** 是交接文档，不是 skill

---

## 6. 触发词

- 「把 xxx skill 放到 xxx」
- 「新建 skill」「装一个 skill」
- 「归档 xxx」「删除 xxx」
- 「分类」「管理 skills」「整理 skills」
