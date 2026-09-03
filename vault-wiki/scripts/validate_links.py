#!/usr/bin/env python3
"""validate_links.py — vault-wiki v8 Step 3：校验笔记里的 [[wikilink]] 全部能跳到真实文件。

规则：
  1. 链接相对路径以笔记所在目录为基准；
  2. 文件扩展名 .md 缺省自动补全；
  3. 支持 `[[path/to/file#Heading]]` 形式 — #Heading 仅校验路径；
  4. 排除纯 URL 内部用 [] 包裹的（不常见，但保险）；
  5. 对链接的 base 目录可通过 --src 指定（默认笔记所在目录）；
  6. 退出码 0 = 0 死链，1 = 有死链（便于 shell 流程判断）。

用法：
    python3 validate_links.py --note /path/to/wiki.md
    python3 validate_links.py --note wiki.md --src /path/to/L2
    python3 validate_links.py --note wiki.md --src /path/to/L2 --strict
"""
import argparse
import os
import re
import sys
from pathlib import Path


# [[xxx]] 匹配；容忍 ] 前可能有空格、点；不含 ![image](...) 形式（图片在 image 域里，不算 wikilink）
WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]\n]+?)\]\]")


def parse_link(target):
    """从 [[path#heading|alias]] 中拆出 path 和 heading。"""
    # 去 alias
    raw = target.split("|", 1)[0].strip()
    # 拆 # heading
    if "#" in raw:
        path_part, heading = raw.split("#", 1)
        path_part = path_part.strip()
        heading = heading.strip()
    else:
        path_part, heading = raw, ""
    return path_part, heading


def resolve_link(link_path, note_path, src_dir):
    """把 wikilink 解析到文件系统绝对路径。返回 Path 或 None(无法解析)。"""
    p = link_path.strip()
    if not p:
        return None

    # 已是绝对路径（极少见，vault 内不应出现）
    if os.path.isabs(p):
        candidate = Path(p)
    else:
        # 优先用 --src；否则以笔记所在目录为基准
        base = src_dir if src_dir else str(note_path.parent)
        # 处理 ../  ./  等
        candidate = (Path(base) / p).resolve()

    # 没写扩展名默认补 .md
    if candidate.suffix == "":
        candidate_md = candidate.with_suffix(".md")
        if candidate_md.exists():
            return candidate_md
    if candidate.exists():
        return candidate
    # 也支持无后缀指向文件夹（罕见）
    if candidate.is_dir():
        return candidate
    return None


def extract_links(text):
    """从 md 文本提取所有 [[...]]。返回 list[(raw, path, heading)]。"""
    out = []
    for m in WIKILINK_RE.finditer(text):
        raw = m.group(0)
        target = m.group(1)
        path, heading = parse_link(target)
        out.append((raw, path, heading))
    return out


def validate_note(note_path, src_dir, strict=False):
    note_path = Path(note_path).resolve()
    if not note_path.is_file():
        raise SystemExit(f"ERROR: note not found: {note_path}")
    text = note_path.read_text(encoding="utf-8", errors="replace")
    links = extract_links(text)
    dead = []
    for raw, link_path, heading in links:
        resolved = resolve_link(link_path, note_path, src_dir)
        if resolved is None:
            dead.append({"raw": raw, "path": link_path, "heading": heading,
                         "reason": "file not found"})
            continue
        # strict 模式额外校验 heading 锚点是否存在
        if strict and heading and resolved.is_file():
            try:
                body = resolved.read_text(encoding="utf-8", errors="replace")
                # 找 # heading 或 ## heading
                pattern = re.compile(
                    r"^#{1,6}\s+" + re.escape(heading) + r"\s*$",
                    re.MULTILINE,
                )
                if not pattern.search(body):
                    dead.append({"raw": raw, "path": link_path, "heading": heading,
                                 "reason": f"heading '{heading}' not found in {resolved.name}"})
            except Exception as e:
                dead.append({"raw": raw, "path": link_path, "heading": heading,
                             "reason": f"read error: {e}"})

    return {
        "note": str(note_path),
        "link_count": len(links),
        "dead_count": len(dead),
        "dead": dead,
    }


def main():
    ap = argparse.ArgumentParser(description="Validate [[wikilink]] in a note (0 dead links)")
    ap.add_argument("--note", required=True, help="path to wiki note .md")
    ap.add_argument("--src", help="base directory for relative links (default: note's dir)")
    ap.add_argument("--strict", action="store_true",
                    help="also validate # heading anchors exist")
    args = ap.parse_args()

    result = validate_note(args.note, args.src, strict=args.strict)

    if result["dead_count"] == 0:
        print(f"OK: 0 dead links ({result['link_count']} checked in {result['note']})")
        sys.exit(0)
    else:
        print(f"FAIL: {result['dead_count']} dead link(s) of {result['link_count']} in {result['note']}")
        for d in result["dead"]:
            print(f"  - {d['raw']}  ({d['reason']})")
        sys.exit(1)


if __name__ == "__main__":
    main()
