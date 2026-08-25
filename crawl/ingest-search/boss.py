#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/boss.py — Boss 直聘关键词搜索 (ominicrawl v1, 搜索型工具层)

crawl_batch(date_yymmdd) → 读飞书 Watchlist ## Boss (boss) 关键词,
对每个关键词调 `opencli boss search`, 写出 notes/boss/<mmdd>_<slug>.md,
返回 [(title, author, md_path, None), ...] (统一契约, images_dir=None)。

依赖: common.opencli_bridge.run_adapter (2026-07-21: 不再注入 NO_PROXY, VPN 自动路由 + 瞬时错误重试)
       common.feishu_watchlist.get_boss_keywords
"""
import sys
from pathlib import Path

SKILL_ROOT = str(Path(__file__).resolve().parent.parent)
for _p in (SKILL_ROOT, str(Path(__file__).parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.paths import notes_dir
from common.feishu_watchlist import get_boss_keywords
from tools._search_common import slugify, mmdd, today_full, search_opencli, write_md

DEFAULT_KEYWORDS = [
    {"kw": "AIBD", "city": "深圳", "label": "AIBD"},
    {"kw": "AI销售", "city": "深圳", "label": "AI销售"},
]
DELAY = 5.0
DAILY_CAP = 30


def _build_md(kw, city, label, results):
    rows = []
    for i, p in enumerate(results, 1):
        title = p.get("name", "")
        salary = p.get("salary", "")
        company = p.get("company", "")
        area = p.get("area", "")
        url = p.get("url", "")
        rows.append(f"| {i} | [{title}]({url}) | {company} | {salary} | {area} |")
    table = (
        "| # | 职位 | 公司 | 薪资 | 城市 |\n"
        "|---|---|---|---|---|\n" + "\n".join(rows)
        if rows else "| （无搜索结果） | | | |"
    )
    d = today_full()
    return (
        f"---\n"
        f'source: boss_search\n'
        f'boss_type: search\n'
        f'title: "{label} 搜索结果"\n'
        f'boss_keyword: "{kw}"\n'
        f'boss_city: "{city or ""}"\n'
        f'collected_at: {d}\n'
        f'boss_result_count: {len(results)}\n'
        f"tags:\n  - boss\n  - 订阅\n"
        f"---\n\n"
        f"# {label} — 搜索结果\n\n"
        f"| 关键词 | {kw} |\n"
        f"| 城市 | {city or '不限'} |\n"
        f"| 搜索时间 | {d} |\n"
        f"| 结果数 | {len(results)} |\n\n"
        f"## 职位列表\n\n{table}\n"
    )


def crawl_batch(date_yymmdd=None):
    """搜索 Boss 全部关键词, 返回结果元组列表。"""
    try:
        keywords = get_boss_keywords()
    except Exception as e:
        print(f"  [warn] 飞书 Boss 关键词读取失败, 用默认: {e}")
        keywords = []
    keywords = keywords or DEFAULT_KEYWORDS

    out_dir = notes_dir() / "boss"
    prefix = mmdd(date_yymmdd)
    out = []
    written = 0
    for item in keywords:
        kw = (item.get("kw") or "").strip()
        if not kw:
            continue
        if written >= DAILY_CAP:
            print("  [cap] 达单日上限, 停止")
            break
        city = (item.get("city") or "").strip()
        label = (item.get("label") or kw).strip()
        slug = slugify(kw, 30)
        out_path = out_dir / f"{prefix}_{slug}.md"
        if out_path.exists():
            print(f"  [skip] {kw} (已存在: {out_path.name})")
            # 已存在也纳入推送(幂等)
            out.append((f"{label} 搜索结果", None, str(out_path), None))
            continue
        print(f"  🔍 Boss 搜索: {kw} (城市={city or '不限'})")
        results = search_opencli(
            ["boss", "search", kw, "--limit", "30", "-f", "json"]
            + (["--city", city] if city else [])
        )
        if not results:
            print(f"  [skip] {kw} 无结果(可能搜索失败, 不写笔记)")
            continue
        _, _, p, _ = write_md(out_dir, f"{prefix}_{slug}.md",
                              _build_md(kw, city, label, results))
        out.append((f"{label} 搜索结果", None, p, None))
        written += 1
    print(f"  ✅ Boss 完成: {len(out)} 个文件")
    return out


if __name__ == "__main__":
    for t in crawl_batch():
        print(t[0], t[2])
