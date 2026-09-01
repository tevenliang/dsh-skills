#!/usr/bin/env python3
"""
dsh-taskboard-cli — DeepSeek Harness 任务看板命令行工具

直接调用 /api/task-board/action API，跳过浏览器 GUI，
配合 Origin 头模拟浏览器同源请求。

需要 dsh web 运行中，且安装了 @linxin666/dsh-client-ui-task-board 插件。
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone, timedelta


def now_ms() -> int:
    return int(datetime.now(timezone(timedelta(hours=8))).timestamp() * 1000)


def post_action(base_url: str, action: dict) -> dict:
    """POST 一个 action 到 /api/task-board/action"""
    envelope = {
        "requestId": str(uuid.uuid4()),
        "action": action,
    }
    body = json.dumps(envelope).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/api/task-board/action",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Origin": base_url,
            "Referer": f"{base_url}/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code}: {body}", file=sys.stderr)
        sys.exit(1)


def get_state(base_url: str) -> dict:
    req = urllib.request.Request(
        f"{base_url}/api/task-board/state",
        method="GET",
        headers={
            "Origin": base_url,
            "Referer": f"{base_url}/",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cmd_list(args):
    state = get_state(args.base_url)
    tasks = state.get("tasks", [])
    if args.status:
        tasks = [t for t in tasks if t.get("status") == args.status]
    print(f"Revision: {state.get('revision')} | Total: {len(state.get('tasks', []))}")
    for t in tasks:
        line = f"  [{t.get('status','?'):>8}] {t.get('title','?'):30} (id: {t.get('id')[:8]})"
        if t.get("schedule"):
            sched = t["schedule"]
            line += f" | cron={sched.get('cron')}"
            nra = sched.get("nextRunAt")
            if nra:
                dt = datetime.fromtimestamp(nra / 1000, tz=timezone(timedelta(hours=8)))
                line += f" next={dt.strftime('%Y-%m-%d %H:%M')}"
        print(line)


def cmd_create(args):
    schedule = None
    if args.cron:
        schedule = {"enabled": True, "cron": args.cron}
    action = {
        "kind": "create",
        "id": args.task_id or str(uuid.uuid4()),
        "input": {
            "title": args.title,
            "description": args.description or "",
            "prompt": args.prompt or "",
        },
    }
    if schedule:
        action["input"]["schedule"] = schedule
    if args.workspace_id:
        action["input"]["workspaceId"] = args.workspace_id
    if args.permission:
        action["input"]["permission"] = args.permission
    resp = post_action(args.base_url, action)
    if resp.get("ok") is False:
        print(f"❌ Failed: {resp.get('error')}", file=sys.stderr)
        sys.exit(1)
    print(f"✅ Created task {action['id']}")
    for t in resp.get("tasks", []):
        if t.get("id") == action["id"]:
            if "schedule" in t:
                nra = t["schedule"].get("nextRunAt")
                if nra:
                    dt = datetime.fromtimestamp(nra / 1000, tz=timezone(timedelta(hours=8)))
                    print(f"   cron={t['schedule'].get('cron')} | 下次运行={dt.strftime('%Y-%m-%d %H:%M:%S')}")
            break


def cmd_schedule(args):
    action = {
        "kind": "set-schedule",
        "taskId": args.task_id,
        "patch": {"enabled": True, "cron": args.cron},
    }
    resp = post_action(args.base_url, action)
    if resp.get("ok") is False:
        print(f"❌ Failed: {resp.get('error')}", file=sys.stderr)
        sys.exit(1)
    for t in resp.get("tasks", []):
        if t.get("id") == args.task_id:
            sched = t.get("schedule", {})
            print(f"✅ Schedule set: cron={sched.get('cron')}")
            nra = sched.get("nextRunAt")
            if nra:
                dt = datetime.fromtimestamp(nra / 1000, tz=timezone(timedelta(hours=8)))
                print(f"   下次运行={dt.strftime('%Y-%m-%d %H:%M:%S')}")
            break


def cmd_delete(args):
    action = {"kind": "delete", "taskId": args.task_id}
    resp = post_action(args.base_url, action)
    if resp.get("ok") is False:
        print(f"❌ Failed: {resp.get('error')}", file=sys.stderr)
        sys.exit(1)
    print(f"✅ Deleted task {args.task_id}")


def cmd_move(args):
    action = {"kind": "move", "taskId": args.task_id, "status": args.status}
    resp = post_action(args.base_url, action)
    if resp.get("ok") is False:
        print(f"❌ Failed: {resp.get('error')}", file=sys.stderr)
        sys.exit(1)
    print(f"✅ Moved to {args.status}")


def cmd_run(args):
    action = {"kind": "run", "taskId": args.task_id}
    resp = post_action(args.base_url, action)
    if resp.get("ok") is False:
        print(f"❌ Failed: {resp.get('error')}", file=sys.stderr)
        sys.exit(1)
    print(f"✅ Triggered run for task {args.task_id}")


def main():
    parser = argparse.ArgumentParser(description="DSH 任务看板命令行工具")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:3080",
        help="DSH Web 访问 URL (默认 http://127.0.0.1:3080)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="列出任务")
    p_list.add_argument("--status", help="按状态过滤 (backlog/todo/running/done/failed)")
    p_list.set_defaults(func=cmd_list)

    p_create = sub.add_parser("create", help="创建任务")
    p_create.add_argument("--task-id", help="指定 task id (默认自动生成)")
    p_create.add_argument("--title", required=True, help="任务标题")
    p_create.add_argument("--description", default="", help="任务描述")
    p_create.add_argument("--prompt", help="发给 agent 的 prompt")
    p_create.add_argument("--cron", help="Cron 表达式, 例如 '30 16 * * *'")
    p_create.add_argument("--workspace-id", help="DSH workspace 列表中的 id")
    p_create.add_argument(
        "--permission",
        choices=["read-only", "workspace-write", "danger-full-access"],
        help="会话权限预设",
    )
    p_create.set_defaults(func=cmd_create)

    p_sched = sub.add_parser("schedule", help="设置/修改任务的 cron")
    p_sched.add_argument("task_id", help="要修改的任务 id")
    p_sched.add_argument("cron", help="新的 cron 表达式, 例如 '30 16 * * *'")
    p_sched.set_defaults(func=cmd_schedule)

    p_del = sub.add_parser("delete", help="删除任务")
    p_del.add_argument("task_id", help="任务 id")
    p_del.set_defaults(func=cmd_delete)

    p_move = sub.add_parser("move", help="移动任务到指定状态列")
    p_move.add_argument("task_id", help="任务 id")
    p_move.add_argument("status", choices=["backlog", "todo", "running", "done", "failed"])
    p_move.set_defaults(func=cmd_move)

    p_run = sub.add_parser("run", help="立即触发任务执行")
    p_run.add_argument("task_id", help="任务 id")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()