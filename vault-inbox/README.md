<div align="center">

# vault-inbox

**一句话，收件箱自动归位 —— Obsidian vault 收件箱批量分类 Skill**

[![Version](https://img.shields.io/badge/version-2.0.0-green)]()

[功能特性](#功能特性) · [三步工作流](#三步工作流) · [双平台](#双平台路径) · [与 vault-notes 的关系](#与-vault-notes-的关系)

</div>

---

## 这是什么

`$VAULT/00_inbox/` 里堆了一堆待处理的 md 笔记？vault-inbox 帮你**批量扫描 → 按规则库 AI 分类 → move 到 vault 数字目录 → 记日志**，全程本地文件操作，不依赖飞书。

原 `feishu-inbox`（飞书 Inbox 收件夹 + 文档库节点树分类搬运），v2.0 起迁移为本地 vault md 后端。

## 功能特性

- **批量扫描** `00_inbox/*.md`，同名去重
- **规则库辅助分类**：读 `rules/categorization_rules.md` + `fewshots/` 纠正案例，AI 判定目标分类
- **关键词启发式**：`classify <file>` 给出快捷建议
- **一键执行**：`apply` 按 JSON 结果 move 文件 + 写 `$VAULT/logs/inbox-move-log.json`
- **纯本地**：无 `lark-cli` / 飞书 API 依赖
- **双平台**：macOS / Linux(VM) 路径自动切换（`$VAULT` 环境变量）

## 与 vault-notes 的关系

| Skill | 职责 |
|-------|------|
| `vault-notes` | 单文件一条龙（总结 + 速读 + 分类） |
| `vault-inbox` | 批量扫描 inbox + 规则库辅助分类 + 去重 + 移动日志 |

两者 classify 落点一致（都 move 到 vault 数字目录）。

## 三步工作流

### 第 0 步 — 扫描

```bash
python3 scripts/vault_inbox.py scan
```

### 第 1 步 — AI 分类

读 `rules/categorization_rules.md` + 相关 `fewshots/`，逐个判定目标目录。可加启发式：

```bash
python3 scripts/vault_inbox.py classify <file>
```

### 第 2 步 — 执行移动

```json
[
  {"file": "xxx.md", "target": "21_ai"},
  {"file": "yyy.md", "target": "23_财富"}
]
```

```bash
python3 scripts/vault_inbox.py apply @result.json
```

执行后每个 md 从 `00_inbox/` move 到对应数字目录，明细追加到 `logs/inbox-move-log.json`。

## 双平台路径

读 `$VAULT` 环境变量，未设按平台回退：

- macOS: `~/Documents/steven_vault`
- Linux/VM: `/home/ubuntu/webdav/steven_vault`

## 注意事项

- 不新建 vault 一级目录，只 move 到现有数字目录
- 移动不可逆，apply 前确认结果 JSON 正确
- 目标目录若已存在同名文件，move 会覆盖

## License

MIT
