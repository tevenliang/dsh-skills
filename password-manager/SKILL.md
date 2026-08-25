---
name: password-manager
description: 密码管家 — 通过 Obsidian vault 本地 MD 文件管理/查询/新增账号密码（双平台
  $VAULT）。触发词：「查询账号」「账号管家」「密码管家」「复制密码」「新增账号」「修改账号」「我的密码」「账号密码」「查密码」
version: 3.0.0
author: Steven Liang
license: MIT
platforms:
  - macos
  - linux
last_modified: 2026-07-19 20:10:00
disable-model-invocation: true
---

# 密码管家 v3.0（Obsidian vault 后端）

> 数据存储：Obsidian vault 本地 MD 文件（`$VAULT/01_my_notes/账号密码.md`），双平台自动解析

## 命令

> 全部走 `password_manager.py`（双平台，自动读 `$VAULT` / `platform.system()` 回退）

```bash
SCRIPT=~/.agents/skills/password-manager/scripts/password_manager.py

# 查询（关键词搜索，默认显示密码）
python3 "$SCRIPT" search <关键词>

# 列出所有分类
python3 "$SCRIPT" categories

# 列出某分类全部记录
python3 "$SCRIPT" list <分类名>

# 复制密码到剪贴板（不输出到终端）
python3 "$SCRIPT" copy <名称>

# 新增记录（分类 + 服务名，然后交互式输入账号/密码/API Key/备注）
python3 "$SCRIPT" add <分类> <服务名>

# 更新某字段
python3 "$SCRIPT" update <服务名> <字段名> <新值>
```

## 安全策略

- `search` / `list` 默认显示密码明文（终端输出）
- `copy` 命令写入剪贴板，终端不输出
- 主存储为本地 vault MD 文件，注意 `$VAULT` 所在磁盘的访问控制（macOS 本机 / VM webdav 挂载）

## 明文存储规范（强制）

- **账号密码文件一律存完整明文凭证，禁止任何掩码/截断**（如 `sk-...xxx`、`sk-or-...a9da` 这类写法严禁写入）
- 写入/导入账号时，API Key、密码、Secret 等必须保留飞书表格或源头的完整原始值，方便用户直接 copy 使用
- 只有当源头本身存的就已是截断值（例如飞书表格里该字段天生只有 `sk-03T...G0cq`）时才照原样存，不得自行再截断
- 任何新增/同步逻辑都不得对凭证做掩码处理

## 双平台路径（vault 根目录）

账号密码文件位于 vault 的 `01_my_notes/账号密码.md`,vault 根目录按运行平台解析:

- 优先读环境变量 `$VAULT`(已设置的平台直接用它)
- 未设置时按系统回退:
  - macOS: `~/Documents/steven_vault`
  - Linux / VM: `/home/ubuntu/webdav/steven_vault`

本 skill 不写死绝对路径,所有引用均为 `$VAULT/01_my_notes/账号密码.md`。

## 本地 MD 文件（主存储）

- 路径：`$VAULT/01_my_notes/账号密码.md`（双平台自动解析，见上方「双平台路径」）
- 2026-07-19 v3.0 起，vault 本地 MD 文件恢复为主存储，取代飞书多维表格
- 飞书多维表格仅保留作历史归档，不再主动写入
