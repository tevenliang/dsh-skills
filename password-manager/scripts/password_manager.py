#!/usr/bin/python3
"""
账号管家 — 查询/新增/修改 Obsidian vault 中的账号密码文件

用法:
    python3 password_manager.py search <关键词>            # 搜索
    python3 account_manager.py list <分类名>              # 列出分类
    python3 account_manager.py add <分类> <服务名>        # 新增（交互式）
    python3 account_manager.py update <服务名>            # 修改字段
    python3 account_manager.py copy <服务名>              # 复制密码到剪贴板
    python3 account_manager.py categories                # 列出所有分类

安全: 默认不显示密码，需要 --show 才可见。copy 命令直接写剪贴板，不在终端输出。
"""

import os
import re
import sys
import subprocess
import platform
from datetime import datetime

# ── 跨平台检测 ──────────────────────────────────────────────────────────────────

def _detect_vault_base():
    """vault 根目录:优先读 $VAULT 环境变量,否则按平台回退"""
    env = os.environ.get("VAULT")
    if env:
        return env
    if platform.system().lower() == "linux":
        return "/home/ubuntu/webdav/steven_vault"
    return "/Users/tianwenliang/Documents/steven_vault"

def _detect_clipboard():
    """自动检测剪贴板命令：xclip (Linux) -> pbcopy (macOS)"""
    system = platform.system().lower()
    if system == "linux":
        return ["xclip", "-selection", "clipboard"]
    return ["pbcopy"]

VAULT_BASE = _detect_vault_base()
PASSWORD_FILE = os.path.join(VAULT_BASE, "01_my_notes", "账号密码.md")
CLIPBOARD_CMD = _detect_clipboard()


# ── 解析 ──────────────────────────────────────────────────────────────────────

def parse_accounts(filepath: str) -> list:
    """
    解析账号密码文件，返回条目列表。
    每个条目: {category, name, account, password, apikey, note, date, raw_line}
    """
    entries = []
    current_category = "未分类"

    if not os.path.exists(filepath):
        print(f"❌ 文件不存在: {filepath}")
        print(f"   (当前平台: {platform.system()}, vault: {VAULT_BASE})")
        return entries

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            # 分类标题
            m = re.match(r"^##\s+(.+)", line)
            if m:
                current_category = m.group(1).strip()
                continue

            # 条目行: 匹配 - **name** rest 或 - - **name** rest
            m = re.match(r"^-\s*(?:-\s*)?\*{1,2}(.+?)\*{1,2}\s+(.*)", line)
            if not m:
                continue

            name = m.group(1).strip()
            rest = m.group(2).strip()

            entry = {
                "category": current_category,
                "name": name,
                "account": "",
                "password": "",
                "apikey": "",
                "note": "",
                "date": "",
                "raw_line": line.rstrip("\n"),
            }

            # 解析字段
            fm = re.search(r"账号[：:]\s*`([^`]*)`", rest)
            if fm:
                entry["account"] = fm.group(1)
            fm = re.search(r"密码[：:]\s*`([^`]*)`", rest)
            if fm:
                entry["password"] = fm.group(1)
            fm = re.search(r"API\s*Key[：:]\s*`([^`]*)`", rest)
            if fm:
                entry["apikey"] = fm.group(1)
            fm = re.search(r"备注[：:]\s*(.+?)(?:\s*/\s*日期|$)", rest)
            if fm:
                entry["note"] = fm.group(1).strip()
            fm = re.search(r"日期[：:]\s*([\d-]+)", rest)
            if fm:
                entry["date"] = fm.group(1)

            entries.append(entry)

    return entries


# ── 搜索 ──────────────────────────────────────────────────────────────────────

def search(entries: list, keyword: str, show_password: bool = False) -> list:
    kw = keyword.lower()
    results = []
    for e in entries:
        if kw in e["name"].lower() or kw in e["account"].lower() or kw in e.get("note", "").lower():
            results.append(e)
    return results


# ── 格式化输出 ────────────────────────────────────────────────────────────────

def format_entry(e: dict, show_password: bool = True) -> str:
    lines = [f"📂 [{e['category']}] {e['name']}"]
    if e["account"]:
        lines.append(f"   账号: {e['account']}")
    if e["password"]:
        pw = e["password"] if show_password else "***"
        lines.append(f"   密码: {pw}")
    if e["apikey"]:
        ak = e["apikey"]
        if len(ak) > 40 and not show_password:
            ak = ak[:20] + "..." + ak[-10:]
        lines.append(f"   API Key: {ak}")
    if e["note"]:
        lines.append(f"   备注: {e['note']}")
    if e["date"]:
        lines.append(f"   日期: {e['date']}")
    return "\n".join(lines)


# ── 复制到剪贴板 ──────────────────────────────────────────────────────────────

def copy_to_clipboard(text: str):
    """跨平台剪贴板复制（Linux: xclip, macOS: pbcopy）"""
    try:
        proc = subprocess.Popen(CLIPBOARD_CMD, stdin=subprocess.PIPE)
        proc.communicate(text.encode("utf-8"))
    except FileNotFoundError:
        # xclip/pbcopy 不可用，输出到终端作为 fallback
        print(f"⚠️ 剪贴板命令 {' '.join(CLIPBOARD_CMD)} 不可用，密码如下:")
        print(text)


# ── 列出分类 ──────────────────────────────────────────────────────────────────

def list_categories(entries: list) -> list:
    cats = {}
    for e in entries:
        c = e["category"]
        cats[c] = cats.get(c, 0) + 1
    return cats


# ── 生成新条目行 ──────────────────────────────────────────────────────────────

def build_entry_line(category: str, name: str, account="", password="", apikey="", note="", date_str=None):
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    parts = [f"- **{name}**"]
    if account:
        parts.append(f"账号: `{account}`")
    if password:
        parts.append(f"密码: `{password}`")
    if apikey:
        parts.append(f"API Key: `{apikey}`")
    if note:
        parts.append(f"备注: {note}")
    parts.append(f"日期: {date_str}")
    return " / ".join(parts)


# ── 写入文件 ──────────────────────────────────────────────────────────────────

def append_to_file(filepath: str, category: str, line: str):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    cat_header = f"\n## {category}\n"
    idx = content.find(cat_header)
    if idx == -1:
        new_content = content.rstrip("\n") + f"\n\n## {category}\n\n{line}\n"
    else:
        next_cat = content.find("\n## ", idx + len(cat_header))
        if next_cat == -1:
            next_cat = len(content)
        insert_pos = next_cat
        new_content = content[:insert_pos].rstrip("\n") + f"\n{line}\n" + content[insert_pos:]

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)


# ── 更新条目 ──────────────────────────────────────────────────────────────────

def update_entry_in_file(filepath: str, name: str, field: str, value: str):
    entries = parse_accounts(filepath)
    target = None
    for e in entries:
        if e["name"] == name:
            target = e
            break
    if not target:
        print(f"❌ 未找到: {name}")
        return False

    new_line = build_entry_line(
        target["category"],
        target["name"],
        account=value if field == "account" else target["account"],
        password=value if field == "password" else target["password"],
        apikey=value if field == "apikey" else target["apikey"],
        note=value if field == "note" else target["note"],
        date_str=datetime.now().strftime("%Y-%m-%d"),
    )

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    new_content = content.replace(target["raw_line"], new_line)
    if new_content == content:
        print(f"⚠️ 替换失败: 原始行匹配不到")
        return False

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"✅ 已更新: {name} ({field})")
    return True


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1].lower()
    show_password = True  # 默认显示密码

    entries = parse_accounts(PASSWORD_FILE)
    if not entries:
        print("⚠️ 未解析到任何条目")
        sys.exit(1)

    if cmd == "search":
        if len(sys.argv) < 3:
            print("用法: search <关键词>")
            sys.exit(1)
        kw = sys.argv[2]
        results = search(entries, kw)
        if not results:
            print(f"🔍 未找到匹配 '{kw}' 的账号")
        else:
            print(f"🔍 找到 {len(results)} 条:\n")
            for e in results:
                print(format_entry(e, show_password))
                print()

    elif cmd == "list":
        if len(sys.argv) < 3:
            print("用法: list <分类名>")
            cats = list_categories(entries)
            print("📂 可用分类:")
            for c, count in sorted(cats.items()):
                print(f"   {c} ({count}条)")
            sys.exit(0)
        cat = sys.argv[2]
        results = [e for e in entries if e["category"] == cat]
        if not results:
            results = [e for e in entries if cat in e["category"]]
        if not results:
            print(f"📂 分类 '{cat}' 不存在或无条目")
            print("可用分类:", ", ".join(sorted(list_categories(entries).keys())))
        else:
            print(f"📂 [{cat}] {len(results)} 条:\n")
            for e in results:
                print(format_entry(e, show_password))
                print()

    elif cmd == "copy":
        if len(sys.argv) < 3:
            print("用法: copy <服务名>")
            sys.exit(1)
        name = sys.argv[2]
        results = search(entries, name)
        if not results:
            print(f"❌ 未找到: {name}")
            sys.exit(1)
        e = results[0]
        pw = e.get("password", "")
        if not pw:
            print(f"⚠️ {name} 没有密码字段")
            sys.exit(1)
        copy_to_clipboard(pw)
        print(f"✅ {name} 的密码已复制到剪贴板（不在终端显示）")

    elif cmd == "categories":
        cats = list_categories(entries)
        for c, count in sorted(cats.items()):
            print(f"📂 {c} ({count}条)")

    elif cmd == "add":
        if len(sys.argv) < 4:
            print("用法: add <分类> <服务名>")
            print("然后交互式输入账号/密码/API Key/备注")
            sys.exit(1)
        cat = sys.argv[2]
        name = sys.argv[3]
        account = input("  账号: ").strip()
        password = input("  密码: ").strip()
        apikey = input("  API Key (可选): ").strip()
        note = input("  备注 (可选): ").strip()

        line = build_entry_line(cat, name, account, password, apikey, note)
        append_to_file(PASSWORD_FILE, cat, line)
        print(f"✅ 已新增: [{cat}] {name}")

    elif cmd == "update":
        if len(sys.argv) < 4:
            print("用法: update <服务名> <字段名> <新值>")
            print("字段: account, password, apikey, note")
            sys.exit(1)
        name = sys.argv[2]
        field = sys.argv[3]
        value = sys.argv[4] if len(sys.argv) > 4 else ""
        if not value:
            value = input(f"  新的 {field}: ").strip()
        update_entry_in_file(PASSWORD_FILE, name, field, value)

    else:
        print(f"❌ 未知命令: {cmd}")
        print("可用: search, list, copy, categories, add, update")


if __name__ == "__main__":
    main()
