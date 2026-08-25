---
name: apple-task-review
description: >
  把最近一个月 macOS 提醒事项的完成情况同步到 vault 的「任务完成log.md」。 触发条件： -
  用户说「更新任务完成log」「同步任务完成情况」「Apple Task Review」 - 用户想 review 最近完成的任务并落盘到 obsidian
  不支持 Windows、Linux；不修改 reminder 本体；只读。
keywords:
  - Apple Task Review
  - apple-task-review
  - task-review
  - 更新任务完成log
  - 同步任务完成情况
  - 任务完成log
  - 任务复盘
examples:
  - 更新任务完成log
  - 同步最近一个月的任务完成情况
  - Apple Task Review
  - apple-task-review
disable-model-invocation: true
---

# Task Review Skill

## 目的

把 macOS Reminders.app 里最近一个月内完成（`isCompleted=true` 且 `completionDate` 在最近 30 天内）的提醒事项，按完成日期分组，追加到 vault 的 `01_my_notes/任务完成log.md` 里。

不做的事：
- 不修改 Reminders.app 里的 reminder
- 不删除 log 条目（每次重写整文件，但保留所有 unique 条目）
- 不覆盖用户已经在 `>>` 后写的备注（去重键含完整 title，含 `>>` 部分）

## 数据源

- macOS Reminders 走 EventKit 框架
- 通过本地编译的 Swift 工具 `~/.local/bin/reminders-cli` 读取
- 子命令 `done-range <startDaysAgo> <endDaysAgo>`，默认 `done-range 29 0`（最近 30 天）
- 判定依据：`completionDate`（**不是 due date**），按用户明确要求

## 输出格式

`01_my_notes/任务完成log.md` 是 YAML-style 列表（sample 风格）：

```markdown
- 20260630
	- 12123申诉>>完成,150块回来了
	- 耳机>>买了redmi抗噪耳机
	- codex手机端连接远程服务器,用账号密码连接?>>搞定,可以双登录
- 20260629
	- 搞linkedin的自动化方案
	- ...
```

注意：
- 顶层 `- YYYYMMDD` 是完成日期，**按日期 desc 排序**（最新在最上）
- 子项 `	- 标题>>[备注]` 用 **tab** 缩进
- `>>` 后的内容是用户在 Reminders.app 里写的"完成备注"（用户可以手补；skill 不会覆盖已有内容）

## 工作流程

### 1. 前置检查

- 确认 `~/.local/bin/reminders-cli` 存在且可执行
- 确认 vault 根目录存在：macOS `~/Documents/steven_vault`；VM/Linux `/home/ubuntu/webdav/steven_vault`；或读 `$VAULT` 环境变量
- 确认目标文件 `01_my_notes/任务完成log.md` 存在（不存在则创建空文件）

### 2. 读已有 log

解析现有 `任务完成log.md`：
- 顶层 `- (\d{8})` 抓日期
- 子项 `	- (.+)` 抓标题全文
- 构造已存在集合 `existing_keys = set((date, title))`

### 3. 拉最近 30 天

跑 `reminders-cli done-range 29 0`，输出格式：

```
OK|range=20260602..20260630|total=132|elapsed=0.59s
DONE|20260630 20:15|<uuid>|生活|耳机>>买了redmi抗噪耳机
DONE|...
```

每行 `DONE|YYYYMMDD HH:mm|<uuid>|<list>|<title>`。

### 4. 去重 + 合并

- 每条 new entry 的 key = `(YYYYMMDD, title)`
- 如果 key 不在 `existing_keys` 里，加入 new_entries
- 合并 `existing + new_entries`，按 `YYYYMMDD` 降序排序（**最新在最上**）

### 5. 写入

**重写整文件**（不是 append），格式：

```
- 20260630
	- 试试验货宝
	- ...
- 20260629
	- ...
```

如果某条 entry 的 title 不含 `>>`，保持原样（用户后续可手补）。

### 6. 报告

输出：

```
OK|scanned=N|existing=M|new=K
added K new entries to 任务完成log.md
date breakdown:
  20260630: +1
  20260629: +12
  ...
```

## 脚本

| 脚本 | 用途 |
|---|---|
| `scripts/update_log.sh` | 跑完整流程：解析已有 log + 拉 30 天 + 去重 + append |

调用方式：直接跑脚本（无需参数），或通过 skill 触发词由 Codex 调用。

## 注意事项

1. **idempotent**：重复跑不会丢失或重复条目，每次都从 done-range 重建 + 与已有合并
2. **整文件重写**：每次跑都会重写整个 log，按日期 desc 排序（最新在最上）
3. **保留 `>>` 备注**：因为去重 key 用 `(date, full title)`，所以已有 `>>` 备注的条目不会被覆盖
4. **只读 Reminders**：不修改 reminder 本体
5. **completionDate 优先**：严格按 `completionDate` 算完成时间，跟 due date 无关
6. **30 天窗口**：done-range 范围 29 0（最近 30 天），超过 30 天的不会自动补充；想要更宽范围改 CLI 参数

## 失败处理

| 错误 | 原因 | 处理 |
|---|---|---|
| reminders-cli 不存在 | Swift 工具没装 | 提示运行 `~/.local/bin/build-reminders-cli.sh` |
| vault 找不到 | 路径不对 | 让用户确认路径 |
| log 文件不可写 | 权限问题 | 让用户检查权限 |
