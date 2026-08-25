#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_today.py — 生成当日每日汇总 md

H1=平台 | H2=博主 | H3=文章标题 | 正文用 ![[]] 嵌入
嵌入路径中 # 编码为 %23（避免 Obsidian 解析为标题锚点）
"""
import re, sys, os
from datetime import date
from pathlib import Path

VAULT_ROOT = Path(os.environ.get("VAULT", "/Users/tianwenliang/Documents/steven_vault"))
SUBSCRIPTION_DIR = VAULT_ROOT / "subscription"

PLATFORM_GROUPS = {
    "douyin":      "抖音",
    "bilibili":    "B站",
    "xiaohongshu": "小红书",
    "boss":        "Boss",
    "jd":          "JD",
    "linkedin":    "领英",
    "tieba":       "贴吧",
    "wechat":      "微信",
}

SKIP_PATTERNS = [r"^hot-archive-", r"^\.", r"^_"]

def should_skip(name):
    return any(re.match(p, name) for p in SKIP_PATTERNS)

def date_matches(name, target):
    if target in name:
        return True
    mmdd = target[5:].replace("-", "")
    yymmdd = target[2:].replace("-", "")
    for p in [mmdd, yymmdd]:
        if f"_{p}" in name or name.startswith(p + "_"):
            return True
    mm = target[5:7]
    dd = target[8:10]
    mmdd_short = mm + dd
    if name.startswith(mmdd_short + "_"):
        return True
    return False

def title_from_file(name):
    name = re.sub(r"^\d{4}-\d{2}-\d{2}[_-]", "", name)
    name = re.sub(r"^\d{2,4}[_-]", "", name)
    name = re.sub(r"\.(md|MD)$", "", name)
    name = re.sub(r"[_-]+", " ", name).strip()
    return name or "无标题"

def embed_path(platform, author, fname):
    if author:
        base = f"subscription/{platform}/{author}/{fname}"
    else:
        base = f"subscription/{platform}/{fname}"
    return base.replace("#", "%23")

def scan_platform(platform, target_date):
    results = []
    pdir = SUBSCRIPTION_DIR / platform
    if not pdir.is_dir():
        return results
    for item in sorted(pdir.iterdir()):
        if item.is_dir():
            for sub in sorted(item.iterdir()):
                if sub.is_file() and sub.suffix == ".md" and not should_skip(sub.name):
                    if date_matches(sub.name, target_date):
                        results.append((item.name, sub.name))
        elif item.is_file() and item.suffix == ".md" and not should_skip(item.name):
            if date_matches(item.name, target_date):
                results.append(("", item.name))
    return results

def generate(target_date):
    lines = []
    total = 0
    for platform, group_name in PLATFORM_GROUPS.items():
        items = scan_platform(platform, target_date)
        if not items:
            continue
        lines.append(f"# {group_name}")
        author_items = {}
        for author, fname in items:
            if author not in author_items:
                author_items[author] = []
            author_items[author].append(fname)
        for author, fnames in sorted(author_items.items()):
            h2 = author or group_name
            lines.append(f"\n## {h2}")
            for fname in fnames:
                title = title_from_file(fname)
                lines.append(f"\n### {title}")
                lines.append(f"\n![[{embed_path(platform, author, fname)}]]")
                total += 1
    return "\n".join(lines).strip(), total

def main():
    target = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime("%Y-%m-%d")
    date_str = target[5:].replace("-", "")
    out = SUBSCRIPTION_DIR / f"{date_str}-index.md"
    content, n = generate(target)
    out.write_text(content + "\n", encoding="utf-8")
    print(f"✅ {out.name}，共 {n} 篇")

if __name__ == "__main__":
    main()
