#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_blocks.py — 解析本地 vault md 文件，输出标题层级结构摘要
用法: python3 parse_blocks.py <md_file>

v2.0 (2026-07-19)：从飞书 docx block fetch 改为本地 md 标题解析。
不再依赖 lark-cli；直接读 md 文件，正则提取 #/##/### 标题层级。
"""
import os
import re
import sys
import platform


def _detect_vault_base():
    env = os.environ.get("VAULT")
    if env:
        return env
    if platform.system().lower() == "linux":
        return "/home/ubuntu/webdav/steven_vault"
    return "/Users/tianwenliang/Documents/steven_vault"


def parse_headings(filepath):
    """从 md 提取标题行（#/##/###... 对应 h1/h2/h3）。返回 [{line, level, text}]。"""
    headings = []
    with open(filepath, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            m = re.match(r"^(#{1,6})\s+(.*)", line.rstrip("\n"))
            if m:
                headings.append({
                    "line": i,
                    "level": len(m.group(1)),
                    "text": m.group(2).strip(),
                })
    return headings


def analyze_structure(headings):
    lines = ["\n## 标题结构概览\n"]
    if not headings:
        return "**⚠️ 未找到任何标题，文档可能缺少结构。**\n"
    prev_level = 0
    issues = []
    for h in headings:
        indent = "  " * (h["level"] - 1)
        if h["level"] - prev_level > 1:
            issues.append(f"  - ⚠️ 第{h['line']}行：{prev_level}级 → {h['level']}级（跳跃）")
        prev_level = h["level"]
        lines.append(f"{indent}- **h{h['level']}** (L{h['line']})：{h['text'][:60]}")
    lines.append("\n**层级分布：**")
    counts = {}
    for h in headings:
        counts[h["level"]] = counts.get(h["level"], 0) + 1
    for k in sorted(counts):
        lines.append(f"  - h{k}：{counts[k]} 个")
    if issues:
        lines.append("\n**检测到的问题：**")
        lines.extend(issues)
    else:
        lines.append("\n✅ 未检测到明显的层级跳跃问题。")
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("用法: python3 parse_blocks.py <md_file>")
        sys.exit(1)
    fp = sys.argv[1]
    if not os.path.exists(fp):
        print(f"❌ 文件不存在: {fp}", file=sys.stderr)
        sys.exit(1)
    headings = parse_headings(fp)
    print("# 文档结构摘要\n")
    print(f"> 来源：`{fp}`")
    print(f"> 标题总数：{len(headings)}\n")
    print(analyze_structure(headings))


if __name__ == "__main__":
    main()
