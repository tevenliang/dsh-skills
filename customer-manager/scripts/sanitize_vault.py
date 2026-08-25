#!/usr/bin/env python3
"""
customer-manager/scripts/sanitize_vault.py

vault md frontmatter 强力规范化 + 备注迁出 frontmatter。

v2.5 设计要点 (2026-08-07 拍板):
  1. 22 业务字段 + 关联issue + tags 全部强制用单引号,避免 YAML 隐式转 int/float/date
  2. 备注字段从 frontmatter 挪到正文段 "## 7. 备注"(用 > 引用块包装),
     整段不再参与 YAML 解析,不再影响 frontmatter 渲染
  3. _ 前缀的 md 不处理(模板/prompt 文件)
  4. 行内字段值里的 markdown 表格/标题/加粗照常清理(沿用 customer-update 的 sanitize_markdown)
  5. frontmatter 字段顺序按 scripts/shared_map.py FIELD_DEFS 严格保持(v2.8 起内嵌,自包含)

v2.6 (2026-08-07) 修复:
  - fix_one 增加 dry_run 参数;dry-run 模式下不再 path.write_text,只报告 changes
  - 变量名 old 改 old_v/new_v 避免 shadow 内置
  - dry-run 仅做"扫描+报告",绝不动磁盘

v2.7 (2026-08-07) 修复:
  - _yaml_value str 分支:含换行的字符串值改用 "|" 块标量
    修复前一版把含换行的字段值强包成单引号字符串,导致 PyYAML 解析失败
    (单引号多行必须每行缩进,块标量每行固定 2 空格缩进更稳)
  - parse_fm 块标量分支已支持该格式,无需修改
  - fix_one 加 _extract_remark_from_body 兜底
    fm 无 备注 字段时从 body 的 "## 7. 备注" 段读回调研报告
    避免 v2.5 → v2.7 round-trip 把调研报告渲染成 "(无)" 丢内容

用法:
  python3 sanitize_vault.py --dry-run
  python3 sanitize_vault.py --dry-run --only 路演中
  python3 sanitize_vault.py --apply
  python3 sanitize_vault.py --apply --only 无锡村田
"""

import argparse
import re
import sys
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

_THIS = Path(__file__).resolve().parent
# 统一合并后所有模块同目录,直接把脚本目录加入 sys.path 即可互相 import
sys.path.insert(0, str(_THIS))

import shared_map  # noqa: E402
from update import sanitize_markdown  # noqa: E402
from field_defs import MULTILINE_FIELDS  # noqa: E402

VAULT_ROOT = Path.home() / "Documents" / "steven_vault"
CUSTOMER_DIR = VAULT_ROOT / "11_customer" / "客户资料"
BACKUP_ROOT = Path.home() / ".cache" / "customer-vault" / "sanitize-backup"

FRONTMATTER_KEYS = [k for _, _, k, _ in shared_map.FIELD_DEFS if k != "备注"] + [
    "关联issue",
    "tags",
]
LIST_KEYS = set(shared_map.LIST_KEYS) | {"关联issue", "tags"}


def _quote(v):
    if v is None:
        v = ""
    return "'" + v.replace(chr(39), chr(39) * 2) + "'"


def _yaml_value(key, raw):
    raw = "" if raw is None else str(raw)
    if key in LIST_KEYS:
        if not raw.strip():
            return "[]"
        items = [ln.strip() for ln in raw.split("\n") if ln.strip()]
        return "[" + ", ".join(_quote(it) for it in items) + "]"
    if not raw:
        return "''"
    # 含换行的 str 值改用 | 块标量,避免单引号字符串多行必须缩进的解析失败
    if "\n" in raw:
        lines = raw.split("\n")
        return "|" + "\n" + "\n".join("  " + ln if ln.strip() else "" for ln in lines)
    return _quote(raw)


def split_fm_body(text):
    lines = text.split("\n")
    if not lines or lines[0].rstrip() != "---":
        return None
    end = None
    for i in range(1, len(lines)):
        if lines[i] == "---" and lines[i] == lines[i].lstrip():
            end = i
            break
    if end is None:
        return None
    return ("\n".join(lines[1:end]), "\n".join(lines[end + 1:]).lstrip("\n"))


def parse_fm(fm_text):
    out = {}
    lines = fm_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^(\S+):\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key, rest = m.group(1), m.group(2).rstrip()
        if rest == "[]":
            out[key] = ""
            i += 1
            continue
        if rest == "|":
            buf = []
            i += 1
            while i < len(lines) and (lines[i] == "" or lines[i][0] in (" ", "\t")):
                buf.append(lines[i])
                i += 1
            stripped = [re.sub(r"^ {0,2}", "", ln) for ln in buf]
            out[key] = "\n".join(stripped).rstrip("\n")
            continue
        if rest.startswith(chr(39)):
            if rest == "''":
                out[key] = ""
                i += 1
                continue
            if rest.endswith(chr(39)) and not rest.endswith("''") and len(rest) >= 2:
                inner = rest[1:-1]
                out[key] = inner.replace("''", chr(39))
                i += 1
                continue
            buf = [rest]
            i += 1
            closed = False
            while i < len(lines):
                buf.append(lines[i])
                accumulated = "\n".join(buf)
                tail = accumulated.rstrip()
                if tail.endswith(chr(39)) and not tail.endswith("''"):
                    nxt = lines[i + 1] if i + 1 < len(lines) else None
                    if nxt is None or nxt.strip() == "---" or (
                        nxt and nxt[0] not in (" ", "\t") and re.match(r"^\S+:", nxt)
                    ):
                        inner = tail[1:-1]
                        out[key] = inner.replace("''", chr(39))
                        i += 1
                        closed = True
                        break
                i += 1
            if not closed:
                inner = "\n".join(buf)[1:].rstrip()
                if inner.endswith(chr(39)) and not inner.endswith("''"):
                    inner = inner[:-1]
                out[key] = inner.replace("''", chr(39))
            continue
        out[key] = rest.strip(chr(39)).strip(chr(34)).replace("''", chr(39))
        i += 1
    return out


def render_fm(values):
    lines = ["---"]
    for key in FRONTMATTER_KEYS:
        v = values.get(key, "")
        lines.append(key + ": " + _yaml_value(key, v))
    lines.append("---")
    return "\n".join(lines)


def render_remark_section(remark_value):
    if not remark_value or not remark_value.strip():
        return "## 7. 备注\n\n(无)\n"
    out = ["## 7. 备注", ""]
    for ln in remark_value.split("\n"):
        if ln.strip():
            out.append("> " + ln)
        else:
            out.append(">")
    return "\n".join(out).rstrip() + "\n"


def clean_value(v, is_remark=False):
    if not v:
        return v
    if is_remark:
        return v.strip("\n")
    return sanitize_markdown(v)


def _extract_remark_from_body(body):
    """
    从 body 提取 "## 7. 备注" 段的内容(去掉 > 前缀)。

    返回纯文本(多行),如果未找到返回空串。
    用于 fix_one 在 fm 无 备注 字段时,从 body 段兜底读取调研报告,
    避免 v2.5 → v2.7 round-trip 时把调研报告渲染成 "(无)" 丢内容。
    """
    m = re.search(r"^## 7\. 备注\s*\n+(.*?)(?=\n## |\Z)", body, re.MULTILINE | re.DOTALL)
    if not m:
        return ""
    raw = m.group(1)
    lines = []
    for ln in raw.split("\n"):
        if ln.startswith("> "):
            lines.append(ln[2:])
        elif ln == ">":
            lines.append("")
        else:
            lines.append(ln)
    text = "\n".join(lines).strip("\n")
    # "(无)" 占位视为空
    if text.strip() == "(无)":
        return ""
    return text


def fix_one(path, dry_run=False):
    """
    规范化单文件:
      1. frontmatter 22 业务字段 + 关联issue/tags 全部强单引号化
      2. 备注 字段从 frontmatter 弹出,渲染到正文段 "## 7. 备注"
      3. 原 body(除 frontmatter + 备注调研报告外)不再保留
         (v2.5 设计:customer-vault 是单向写入,vault md 只保留 frontmatter + 调研报告)
    dry_run=True 时只报告 changes,不写文件。
    """
    text = path.read_text()
    parts = split_fm_body(text)
    if parts is None:
        return False, ["fm_missing"]
    fm_text, body = parts
    fm = parse_fm(fm_text)
    if not fm:
        return False, ["fm_empty"]
    changes = []
    remark_raw = fm.pop("备注", "")
    # 兜底:v2.5 之后 fm 已无 备注 字段,调研报告落到 body 的 "## 7. 备注" 段
    # 避免 v2.5 → v2.7 round-trip 时把调研报告渲染成 "(无)" 丢内容
    if not remark_raw.strip():
        remark_raw = _extract_remark_from_body(body)
    for key in list(fm.keys()):
        if key in {"关联issue", "tags"}:
            continue
        old_v = fm.get(key, "") or ""
        new_v = clean_value(old_v, is_remark=False)
        if new_v != old_v:
            changes.append(key + ": clean " + str(len(old_v)) + "->" + str(len(new_v)))
            fm[key] = new_v
    new_fm = render_fm(fm)
    remark_section = render_remark_section(clean_value(remark_raw, is_remark=True))
    if body.strip():
        changes.append("drop body (frontmatter only)")
    new_text = new_fm + "\n\n" + remark_section
    if new_text.rstrip() != text.rstrip():
        if not dry_run:
            path.write_text(new_text)
        return True, changes
    return False, changes


def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    p.add_argument("--only")
    args = p.parse_args()
    if not args.dry_run and not args.apply:
        args.dry_run = True
    if not CUSTOMER_DIR.exists():
        print("missing dir", CUSTOMER_DIR)
        return 1
    files = sorted(p for p in CUSTOMER_DIR.glob("*.md") if not p.name.startswith("_"))
    if args.only:
        files = [p for p in files if args.only in p.name]
    print("scan", len(files), "files (skip _*); mode=", "apply" if args.apply else "dry-run")
    touched = []
    skipped = []
    for f in files:
        try:
            changed, changes = fix_one(f, dry_run=args.dry_run)
        except Exception as e:
            skipped.append((f, type(e).__name__ + ": " + str(e)))
            continue
        if changed:
            touched.append((f, changes))
    for f, ch in touched[:20]:
        print("-- " + f.name)
        for c in ch:
            print("   . " + c)
    if len(touched) > 20:
        print("   ... +" + str(len(touched) - 20) + " more")
    for f, why in skipped:
        print("!! " + f.name + ": " + why)
    print()
    print("summary: total=" + str(len(files)) + " changed=" + str(len(touched)) + " skipped=" + str(len(skipped)))
    if not touched:
        return 0
    if args.dry_run:
        print("dry-run only; re-run with --apply to write")
        return 0
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = BACKUP_ROOT / ts
    backup_dir.mkdir(parents=True, exist_ok=True)
    for f, _ in touched:
        rel = f.relative_to(VAULT_ROOT)
        blob = subprocess.run(
            ["git", "-C", str(VAULT_ROOT), "show", "HEAD:" + str(rel)],
            capture_output=True, check=False,
        )
        if blob.returncode == 0:
            (backup_dir / f.name).write_bytes(blob.stdout)
        else:
            shutil.copy2(f, backup_dir / f.name)
    print("backup ->", backup_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
