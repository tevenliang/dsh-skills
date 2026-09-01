#!/usr/bin/env python3
"""_gen_index.py — supervisor 调用的 index 生成工具（走 Mac 本地 vault，WebDAV 同步后状态）。

每次跑批结束后重建「今天」和「昨天」的 index（覆盖式），确保 VM 回填的文章也被补进 index。
"""
import os, sys, subprocess
from pathlib import Path

CRAWL_ROOT = Path(__file__).resolve().parent.parent   # ~/.agents/skills/crawl
VAULT = Path(os.environ.get("VAULT", "~/Documents/steven_vault")).expanduser()
GEN_TODAY = CRAWL_ROOT / "common-today" / "gen_today.py"

PY = sys.executable


def regenerate_index(date: str, dry_run: bool = False):
    """重建指定日期的 index.md（走 Mac 本地 vault）。"""
    if not GEN_TODAY.exists():
        print(f"  ⚠️ gen_today.py 不存在，跳过 index 生成")
        return False
    if not (VAULT / "subscription").exists():
        print(f"  ⚠️ vault subscription 目录不存在，跳过")
        return False
    if dry_run:
        print(f"  🔍 [dry-run] 重建 {date} index")
        return True
    env = dict(os.environ)
    env["VAULT"] = str(VAULT)
    rc = subprocess.run([PY, str(GEN_TODAY), date],
                        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT).returncode
    return rc == 0


def regenerate_recent(days: int = 2, dry_run: bool = False):
    """重建最近 N 天的 index（今天 + 昨天），覆盖 VM 回填遗漏。"""
    from datetime import date, timedelta
    today = date.today()
    dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    ok = True
    for d in dates:
        print(f"  📄 重建 {d} index ...", flush=True)
        if not regenerate_index(d, dry_run=dry_run):
            ok = False
    return ok


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--date", help="重建指定日期 YYYY-MM-DD")
    p.add_argument("--recent", type=int, default=0, help="重建最近 N 天")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if args.date:
        regenerate_index(args.date, dry_run=args.dry_run)
    elif args.recent:
        regenerate_recent(args.recent, dry_run=args.dry_run)
    else:
        regenerate_recent(dry_run=args.dry_run)
