#!/usr/bin/env python3
"""
backfill_summary.py — 补 vault md 缺的 ## 总结 段 (2026-08-07 治本 #24)

设计:
- 扫 vault/subscription/{bilibili,douyin}/ 下所有 md
- 检测 ## 总结 段缺失 + 正文 ≥ 100 字 的 md
- 调 GLM summarize() + inject_summary_to_md() 注入

触发场景:
- supervisor.recovery retry 转录后没补 summary (ASP H撞线后 wav 补转录 → summary跳过)
- 历史 backfill 漏掉的 md (backfill_pending 2026-08-07 之前没调 summary)
- GLM 解析失败 (JSON 不全 / API 偶发问题)

不做 wav 转录! 这是补"已存在正文但缺总结"的 md, 不是补 wav。

用法:
  python3 tools/backfill_summary.py --dry-run                # 列出待补 md
  python3 tools/backfill_summary.py --date 2026-08-06       # 只补 8/6 的
  python3 tools/backfill_summary.py --max 3                  # POC 3 条
  python3 tools/backfill_summary.py                          # 全跑
"""
import argparse
import os
import re
import sys
from pathlib import Path

CRAWL_ROOT = Path(__file__).resolve().parent.parent
VAULT_DEFAULT = Path(os.path.expanduser("~/Documents/steven_vault"))

# 2026-08-07: 直接复用 common-summary/summarize.py (GLM API + inject_summary_to_md)
sys.path.insert(0, str(CRAWL_ROOT / "common-summary"))
from summarize import summarize, inject_summary_to_md, has_summary_section


def get_transcript_length(md_path: Path) -> int:
    """取 ## 转录 段字符数."""
    try:
        text = md_path.read_text(encoding='utf-8', errors='replace')
    except Exception:
        return 0
    m = re.search(r"##\s*转录\s*\n+(.*?)(?=\n##|\Z)", text, re.DOTALL)
    if not m:
        return 0
    return len(m.group(1).strip())


def scan_pending(vault_root: Path, date_filter: str = None) -> list:
    """扫 vault/subscription/{bilibili,douyin}/ 下所有缺 ## 总结 + 正文 ≥ 100 字 的 md."""
    pending = []
    for plat in ("bilibili", "douyin"):
        plat_dir = vault_root / "subscription" / plat
        if not plat_dir.is_dir():
            continue
        for md in sorted(plat_dir.rglob("*.md")):
            # 跳过 .DS_Store / hidden
            if md.name.startswith(".") or md.name.startswith("_archive"):
                continue
            # 日期过滤 (按文件名 yyyy-mm-dd 前缀)
            if date_filter and not md.name.startswith(date_filter):
                continue
            if has_summary_section(md):
                continue
            tlen = get_transcript_length(md)
            if tlen < 100:
                continue
            pending.append((plat, md, tlen))
    return pending


def process_one(plat: str, md_path: Path) -> tuple:
    """给一个 md 补 ## 总结. 返回 (success, message)."""
    try:
        obj = summarize(md_path)
        summary = obj.get("summary", "")
        topics = obj.get("topics", [])
        if not summary or not topics:
            return False, "总结 JSON 缺 summary/topics"
        inject_summary_to_md(md_path, obj, overwrite=True)
        return True, f"📌 {summary[:30]}... ({len(topics)} 条要点)"
    except Exception as e:
        return False, f"GLM 异常: {str(e)[:120]}"


def main():
    p = argparse.ArgumentParser(description="backfill 缺的 ## 总结 段")
    p.add_argument("--vault", default=str(VAULT_DEFAULT))
    p.add_argument("--date", default=None, help="只补该日期 (yyyy-mm-dd) 的 md")
    p.add_argument("--max", type=int, default=None, help="最多处理几个 (POC)")
    p.add_argument("--platform", choices=["bilibili", "douyin"], default=None)
    p.add_argument("--dry-run", action="store_true", help="只列出待补 md, 不调 GLM")
    args = p.parse_args()

    vault_root = Path(args.vault)
    if not vault_root.is_dir():
        print(f"❌ vault 不存在: {vault_root}")
        return 1

    pending = scan_pending(vault_root, args.date)
    if args.platform:
        pending = [p for p in pending if p[0] == args.platform]

    print(f"=== 待 backfill 总结: {len(pending)} 篇 ===")
    for plat, md, tlen in pending:
        rel = md.relative_to(vault_root)
        print(f"  [{plat}] {rel} (正文 {tlen}字)")

    if args.dry_run:
        if args.max:
            print(f"\n--max {args.max}: 本次会补 {min(len(pending), args.max)} 篇")
        else:
            print(f"\n本次会补全部 {len(pending)} 篇")
        return 0

    targets = pending[:args.max] if args.max else pending
    n_ok = n_fail = 0
    for i, (plat, md, tlen) in enumerate(targets, 1):
        rel = md.relative_to(vault_root)
        print(f"\n[{i}/{len(targets)}] 🤖 [{plat}] {rel.name[:40]}")
        ok, msg = process_one(plat, md)
        if ok:
            n_ok += 1
            print(f"  ✅ {msg}")
        else:
            n_fail += 1
            print(f"  ⚠️ {msg}")

    print(f"\n=== 完成: 成功 {n_ok} / 失败 {n_fail} / 总 {len(targets)} ===")
    return 0 if n_fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
