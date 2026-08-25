#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vault_inbox.py — vault-inbox 核心：扫描 00_inbox 的 md, 辅助分类, move 到数字目录, 记日志。

双平台：读 $VAULT 环境变量，未设按 platform.system() 回退。
  - macOS: /Users/tianwenliang/Documents/steven_vault
  - Linux/VM: /home/ubuntu/webdav/steven_vault

命令：
  scan                          列出 00_inbox/*.md（文件名/首标题/大小）
  classify <file>               对单文件给关键词启发式建议分类
  apply <result_json|@file>     读取 [{file,target}] 结果，move 到对应目录 + 记日志

本地版不调用 lark-cli / 飞书 API。最终分类由 agent 读 rules/ + fewshots/ 后决定。
"""
import os
import sys
import json
import shutil
import platform
import re
from datetime import datetime


def _detect_vault_base():
    env = os.environ.get("VAULT")
    if env:
        return env
    if platform.system().lower() == "linux":
        return "/home/ubuntu/webdav/steven_vault"
    return "/Users/tianwenliang/Documents/steven_vault"


VAULT = _detect_vault_base()
INBOX = os.path.join(VAULT, "00_inbox")
LOG_DIR = os.path.join(VAULT, "logs")

# 分类 → vault 相对目录（与 vault-notes 一致）
CAT = {
    "读书笔记": "24_阅读思考", "访谈播客": "24_阅读思考", "思维方法论": "24_阅读思考",
    "销售技巧": "26_销售", "Agent应用": "21_ai", "应用工具": "22_应用工具",
    "职场故事": "25_职业", "新闻资讯": "13_资讯", "产品方案": "12_产品方案",
    "客户资料": "11_customer", "极狐工作": "02_work_notes", "项目管理": "02_work_notes",
    "其它工作": "02_work_notes", "投资理财": "23_财富", "基金股票": "23_财富",
    "社保医保": "31_家庭生活", "公积金个税": "31_家庭生活", "健康健身": "31_家庭生活",
    "房产装修": "31_家庭生活", "家庭教育": "31_家庭生活", "休闲娱乐": "31_家庭生活",
    "其它生活": "32_未分类",
}

# 简单关键词启发式（辅助建议，非最终判定；最终由 agent 读 rules/ 决定）
KEYWORDS = {
    "投资理财": ["基金", "股票", "理财", "个股", "A股", "美股", "养基"],
    "新闻资讯": ["腾讯", "大厂", "企业动态", "财报", "公司"],
    "Agent应用": ["LLM", "大模型", "Claude", "Codex", "Hermes", "Agent", "Prompt", "CLI", "OpenClaw"],
    "应用工具": ["Obsidian", "WPS", "浏览器", "Mac", "Windows", "云服务", "App", "插件"],
    "产品方案": ["产品", "方案", "GitLab", "MaaS"],
    "读书笔记": ["读书", "书评", "读后感"],
    "思维方法论": ["方法论", "思维模型", "认知"],
    "访谈播客": ["访谈", "播客", "对谈"],
    "销售技巧": ["销售", "话术", "客户"],
    "职场故事": ["求职", "面试", "职场", "转型"],
    "健康健身": ["健身", "医保", "社保", "腰椎"],
    "家庭教育": ["育儿", "亲子", "教育"],
    "房产装修": ["房产", "装修", "房贷"],
}


def _first_heading_and_text(filepath, max_chars=2000):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read(max_chars)
    except Exception:
        return "", ""
    heading = ""
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if m:
        heading = m.group(1).strip()
    return heading, text


def suggest_category(filepath):
    heading, text = _first_heading_and_text(filepath)
    blob = (heading + "\n" + text).lower()
    scores = {}
    for cat, kws in KEYWORDS.items():
        s = sum(1 for kw in kws if kw.lower() in blob)
        if s:
            scores[cat] = s
    if not scores:
        return "其它生活", "无关键词命中，建议人工判定或归未分类"
    best = max(scores, key=scores.get)
    return best, f"关键词命中: {scores}"


def scan():
    if not os.path.isdir(INBOX):
        print(json.dumps({"error": f"inbox 不存在: {INBOX}"}, ensure_ascii=False))
        return
    result = []
    seen = set()
    for fn in sorted(os.listdir(INBOX)):
        if not fn.endswith(".md"):
            continue
        if fn in seen:  # 同名去重，只处理一次
            continue
        seen.add(fn)
        p = os.path.join(INBOX, fn)
        heading, _ = _first_heading_and_text(p)
        size = os.path.getsize(p)
        result.append({"file": fn, "first_heading": heading, "size": size})
    print(json.dumps(result, ensure_ascii=False, indent=2))


def classify_one(filepath):
    cat, reason = suggest_category(filepath)
    print(json.dumps({"file": os.path.basename(filepath), "suggestion": cat, "reason": reason}, ensure_ascii=False))


def apply_moves(result_arg):
    if result_arg.startswith("@"):
        data = json.loads(open(result_arg[1:]).read())
    else:
        data = json.loads(result_arg)
    if not isinstance(data, list):
        print(json.dumps({"ok": False, "msg": "result 必须是 [{file,target}] 数组"}, ensure_ascii=False))
        return
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, "inbox-move-log.json")
    journal = {"started_at": datetime.now().isoformat(timespec="seconds"), "moves": []}
    ok = 0
    for item in data:
        fn = item.get("file")
        target = item.get("target")
        if target not in CAT:
            journal["moves"].append({"file": fn, "target": target, "status": "failed", "error": "未知分类"})
            continue
        src = os.path.join(INBOX, fn)
        if not os.path.exists(src):
            journal["moves"].append({"file": fn, "target": target, "status": "failed", "error": "源文件不存在"})
            continue
        dst_dir = os.path.join(VAULT, CAT[target])
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, fn)
        shutil.move(src, dst)
        journal["moves"].append({"file": fn, "target": target, "status": "moved", "dest": dst})
        ok += 1
    journal["finished_at"] = datetime.now().isoformat(timespec="seconds")
    journal["summary"] = {"planned": len(data), "moved": ok}
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(journal, f, ensure_ascii=False, indent=2)
    print(json.dumps({"ok": True, "moved": ok, "log": log_path}, ensure_ascii=False))


def main():
    args = sys.argv[1:]
    if not args:
        print("usage: vault_inbox.py <scan|classify <file>|apply <json|@file>>")
        sys.exit(1)
    cmd = args[0]
    if cmd == "scan":
        scan()
    elif cmd == "classify":
        classify_one(args[1])
    elif cmd == "apply":
        apply_moves(args[1])
    else:
        print("unknown cmd:", cmd)
        sys.exit(1)


if __name__ == "__main__":
    main()
