---
name: vault-inbox
version: 2.0.0
description: Obsidian vault 收件箱批量分类 — 扫描 00_inbox 的 md，按规则库 AI 分类，move 到 vault
  数字目录并记录日志。触发词：「收拾 inbox」「分类收件箱」「整理 inbox」「vault-inbox」。
author: Steven Liang
license: MIT
platforms:
  - macos
  - linux
disable-model-invocation: true
---

# vault-inbox v2.0 — vault 收件箱批量分类

> **v2.0 (2026-07-19)**：从飞书 Inbox 收件夹 + 文档库节点树迁移为本地 vault md 后端，去除 `lark-cli` / 飞书 API 依赖。原 `feishu-inbox`。

## 定位

把 `$VAULT/00_inbox/` 里待处理的 md 笔记，按分类规则库（rules/ + fewshots/）AI 判定目标分类，move 到对应的 vault 数字目录，并记录移动日志。

**与 vault 其他 skill 的边界**：`vault-summary` 负责长内容蒸馏总结（不落盘），`vault-structure` 负责单文件标题结构重构（不搬运）。`vault-inbox` 专注**批量扫描 inbox + 规则库辅助分类 + 去重 + 台账 + move 到数字目录**，三者可在同一篇笔记上按需接力使用。

## 双平台路径

vault 根目录读 `$VAULT` 环境变量，未设按平台回退：
- macOS: `~/Documents/steven_vault`
- Linux/VM: `/home/ubuntu/webdav/steven_vault`

## 分类映射

| 内容判定 | 目标目录 |
|----------|----------|
| 书籍/读书笔记 | `24_阅读思考` |
| 创始人/CEO 访谈、播客 | `24_阅读思考` |
| 方法论、思维模型 | `24_阅读思考` |
| 销售经历/话术/战术 | `26_销售` |
| AI 大模型(llm/agent/coding/prompt)、Hermes/Codex/Claude/CLI | `21_ai` |
| AI 工具/CLI/技能平台/WorkBuddy/飞书/扣子/macOS/软件应用 | `22_应用工具` |
| 转型/职场/求职面试 | `25_职业` |
| 行业/企业/经济/社会/人物资讯 | `13_资讯` |
| GitLab/CodeRider/MaaS/产品方案/企业软件 | `12_产品方案` |
| 客户资料 | `11_customer` |
| 极狐工作/项目管理/其它工作 | `02_work_notes` |
| 股票/基金/理财/房产/个税/保险/创业 | `23_财富` |
| 社保/医保/健身/腰椎 | `31_家庭生活` |
| 家庭教育/亲子 | `31_家庭生活` |
| 旅游/购物/游戏/夫妻 | `31_家庭生活` |
| 其它 | `32_未分类` |

> 运行时以 `scripts/vault_inbox.py` 的 `CAT` 字典为准。

## 规则库（保留，与飞书无关）

- `rules/categorization_rules.md`：分类规则 + 关键词速查表（Steven 维护，纠正后增量追加）
- `fewshots/corrections_*.md`：纠正案例（按日期命名），AI 分类时作为 few-shot 参考

## 三步工作流

### 第 0 步 — 扫描 inbox

```bash
python3 scripts/vault_inbox.py scan
```

列出 `$VAULT/00_inbox/*.md`（文件名 / 首标题 / 大小），同名去重。

### 第 1 步 — AI 分类（对照 rules + fewshots）

逐个文件，读 `rules/categorization_rules.md` + 相关 `fewshots/`，结合文件名/首标题/内容，判目标分类。

可用辅助启发式：
```bash
python3 scripts/vault_inbox.py classify <file>   # 输出关键词建议分类
```

### 第 2 步 — 写结果 + 执行移动

把分类结果写成 JSON 数组，交给 `apply` 执行（move + 记日志）：

```json
[
  {"file": "xxx.md", "target": "21_ai"},
  {"file": "yyy.md", "target": "23_财富"}
]
```

```bash
python3 scripts/vault_inbox.py apply @result.json
# 或直接传 JSON 串
python3 scripts/vault_inbox.py apply '[{"file":"xxx.md","target":"21_ai"}]'
```

执行后：
- 每个 md 从 `$VAULT/00_inbox/` move 到 `$VAULT/<CAT[target]>/`
- 移动明细追加到 `$VAULT/logs/inbox-move-log.json`

## 去重规则

- 同名文件只处理一次（scan 已去重）
- 目标目录若已存在同名文件，move 会覆盖——执行前确认

## 注意事项

- 不新建 vault 一级目录，只 move 到现有数字目录
- 最终分类由 agent（LLM）结合 rules/fewshots 决定，`classify` 仅给启发式建议
- 移动不可逆，执行 `apply` 前确认结果 JSON 正确
- 无飞书依赖，纯本地文件操作

## 更新记录

- v1.0：feishu-inbox，飞书 Inbox 收件夹 + 文档库节点树分类搬运
- 2026-07-19：v2.0 迁移为本地 vault md 后端，去 lark-cli，核心重写 vault_inbox.py，删除飞书上传脚本，目录归位 `skills/PRODUCTIVITY/vault-inbox`
