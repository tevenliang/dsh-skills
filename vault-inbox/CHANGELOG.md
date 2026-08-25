# Changelog

## [2.0.0] - 2026-07-19

### Changed
- 从飞书 Inbox 收件夹 + 文档库节点树迁移为本地 Obsidian vault md 后端
- 去除 `lark-cli` / 飞书 API 全部依赖，纯本地文件操作
- 核心脚本重写为 `scripts/vault_inbox.py`（scan / classify / apply 三命令）
- 双平台路径：读 `$VAULT` 环境变量，未设按 macOS / Linux(VM) 回退
- 移动日志落 `$VAULT/logs/inbox-move-log.json`

### Removed
- 飞书上传脚本（lark_api / pdf_upload / smart_upload / mover / inbox_classify 等）
- 飞书配置（`config/wiki_nodes.json`、飞书 doc 元数据 `scripts/inbox_docs.json`）
- 飞书文档库结构文档、节点字段说明、生成式 reports/

### Added
- `rules/categorization_rules.md`：分类规则 + 关键词速查表（保留可用性）
- `fewshots/corrections_*.md`：纠正案例库（AI 分类 few-shot 参考）

---

## [1.0.0] - 2026-04 (feishu-inbox)

> 原飞书版历史（2.3.1 及之前）已随迁移废弃，不在此追溯。
