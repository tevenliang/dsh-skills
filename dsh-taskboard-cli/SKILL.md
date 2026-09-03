---
name: dsh-taskboard-cli
metadata:
  version: 1.0.0
description: >
  DeepSeek Harness (DSH) 任务看板 (@linxin666/dsh-client-ui-task-board) 命令行客户端。
  直接调用 /api/task-board/action API 跳过浏览器 GUI 创建/修改/删除/触发任务。
  配合 Origin 头模拟浏览器同源请求，无需 Playwright 等浏览器自动化。
disable-model-invocation: true
---

# dsh-taskboard-cli — DSH 任务看板命令行工具

DSH 的任务看板插件 (`@linxin666/dsh-client-ui-task-board`) 默认只能通过浏览器 Web GUI 创建任务。本工具通过直接调用 host 上的 `/api/task-board/action` HTTP API（带浏览器同源标记），无需打开浏览器或安装 Playwright。

## 前置条件

- DSH web 服务运行中（`dsh web --port 3080`）
- 已安装 `@linxin666/dsh-client-ui-task-board` 插件（`dsh plugin --profile web add @linxin666/dsh-client-ui-task-board`）
- Python 3.8+

## 用法

```bash
# 列任务
python3 ~/.dsh/skills/dsh-taskboard-cli/scripts/task-board-cli.py list

# 只看 todo 状态的任务
python3 ~/.dsh/skills/dsh-taskboard-cli/scripts/task-board-cli.py list --status todo

# 创建任务：每日 16:30 跑 aihot
python3 ~/.dsh/skills/dsh-taskboard-cli/scripts/task-board-cli.py create \
  --title "每日 AI 热点简报" \
  --description "每天16:30自动调用/aihot生成当日AI热点资讯" \
  --prompt "请调用 /aihot 查询今日 AI 热点资讯，整理成中文 markdown 格式输出，直接输出结果即可。" \
  --cron "30 16 * * *"

# 修改已有任务的 cron
python3 ~/.dsh/skills/dsh-taskboard-cli/scripts/task-board-cli.py schedule <task-id> "0 */2 * * *"

# 移动任务到 running 状态
python3 ~/.dsh/skills/dsh-taskboard-cli/scripts/task-board-cli.py move <task-id> running

# 立即触发任务
python3 ~/.dsh/skills/dsh-taskboard-cli/scripts/task-board-cli.py run <task-id>

# 删除任务
python3 ~/.dsh/skills/dsh-taskboard-cli/scripts/task-board-cli.py delete <task-id>

# 连远端 DSH（VM）
python3 ~/.dsh/skills/dsh-taskboard-cli/scripts/task-board-cli.py --base-url http://127.0.0.1:3090 list
```

## 命令清单

| 命令 | 作用 |
|------|------|
| `list [--status X]` | 列所有任务（可按状态过滤） |
| `create --title X [--description Y] [--prompt Z] [--cron C] [--workspace-id ID] [--permission P]` | 创建任务 |
| `schedule <task-id> <cron>` | 设置/修改任务的 cron |
| `delete <task-id>` | 删除任务 |
| `move <task-id> <status>` | 移动任务状态列 (backlog/todo/running/done/failed) |
| `run <task-id>` | 立即触发一次任务执行 |

## Cron 格式

5 段式：`分 时 日 月 周`
- `30 16 * * *` = 每天 16:30
- `0 9 * * 1-5` = 工作日 9:00
- `0 */2 * * *` = 每 2 小时整点
- `0 9,18 * * *` = 每天 9:00 和 18:00

## 工作原理

DSH 任务看板是 **Host-authoritative** 架构：
- 账本缓存在 Host 进程内存
- 文件 (`~/.dsh/task-board/ledger-v2.json`) 只是持久化快照
- 直接编辑文件无效，必须通过 API 改内存

API 路由：
- `GET  /api/task-board/state` — 读状态
- `POST /api/task-board/action` — 改任务

API 认证：必须带浏览器同源标记（`Origin: <base-url>`），否则返回 403。

## 注意

- 不要直接编辑 `~/.dsh/task-board/ledger-v2.json`，Host 启动时会用内存状态覆盖文件
- 任务执行需要 DSH 端关联有可用的 workspace（通过 `--workspace-id` 指定）
- `permission` 默认 `read-only`，设更高权限需要手动确认（`confirm-permission` action）
- VM 上 DSH 必须安装了 `@linxin666/dsh-client-ui-task-board` 插件才能用本工具