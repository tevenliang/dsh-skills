#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/tieba.py — 百度贴吧帖子抓取 (ominicrawl v3, aiotieba 异步 API 方案)

crawl_batch(date_yymmdd) → 读飞书 Watchlist ## 贴吧 (tieba) 吧名,
对每个吧调 aiotieba.Client.get_threads + get_posts (无需登录，无需 Chrome),
写出 notes/tieba/<forum>/<mmdd>_<slug>.md + media/tieba/<tid>/ 下的图片,
返回 [(title, md_path, None), ...] (按帖子逐条)。
"""
import asyncio
import dataclasses
import sys
import time
from pathlib import Path

SKILL_ROOT = str(Path(__file__).resolve().parent.parent)
for _p in (SKILL_ROOT, str(Path(__file__).parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import aiotieba
import datetime
import httpx
import os
import re

from common.paths import notes_dir, media_dir, project_root
from common.feishu_watchlist import get_tieba_forums
from tools._search_common import slugify

DEFAULT_FORUMS = ["少年西游记"]
PAGES = 1
THREAD_LIMIT = 10  # 每吧最多抓多少帖           # 每吧翻几页（首页即最新）
MEDIA_TIEBA = media_dir() / "tieba"  # media/tieba/<tid>/


# ── 内容渲染 ────────────────────────────────────────────────

def _render_contents(contents) -> str:
    """把 Contents_p / Contents_t 渲染成纯文本/图片 markdown。
    FragText → 纯文本
    FragImage_p/t → 下载到 media/tieba/<tid>/ 并返回 ![](local) 或 fallback URL
    FragLink → [title](url)
    FragEmoji → [desc]
    """
    if not contents or not hasattr(contents, "objs"):
        return ""
    parts = []
    for obj in contents.objs:
        tn = type(obj).__name__
        if tn == "FragText":
            parts.append(obj.text)
        elif tn in ("FragImage_p", "FragImage_t"):
            # 下载到本地，Feishu markdown 直接渲染本地相对路径图片
            img_md = _download_image(obj)
            if img_md:
                parts.append(img_md)
        elif tn == "FragLink":
            url = (getattr(obj, "raw_url", None) or "")
            if hasattr(url, "__str__"):
                url = str(url)
            title = getattr(obj, "title", "") or ""
            if url:
                parts.append(f"[{title}]({url})" if title else url)
        elif tn == "FragEmoji":
            desc = getattr(obj, "desc", "") or ""
            if desc:
                parts.append(f"[{desc}]")
    return "".join(parts)


# ── 图片下载 ─────────────────────────────────────────────────

def _download_image(frag) -> str:
    """下载贴吧图片到 media/tieba/，返回 markdown 图片引用。
    优先下载到本地，写 ![hash](tieba/xxx.jpg)；
    下载失败时用 CDN URL 写 ![hash](https://...)。
    """
    url = (
        getattr(frag, "origin_src", None)
        or getattr(frag, "big_src", None)
        or getattr(frag, "src", None)
    )
    if not url:
        return ""
    url = str(url).strip()
    if not url:
        return ""

    img_hash = getattr(frag, "hash", None) or str(hash(url))[:16]

    # 用 URL 的 path 部分（不含 query string）作文件名，避免路径含 ?
    from urllib.parse import urlparse
    parsed = urlparse(url)
    path_part = parsed.path  # /forum/pic/item/xxx.jpg
    fname = path_part.split("/")[-1] or f"{img_hash}.jpg"
    if not fname.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
        fname = f"{img_hash}.jpg"

    # 统一放 media/tieba/<fname>
    img_dir = MEDIA_TIEBA
    img_path = img_dir / fname

    if img_path.exists():
        # 用 Obsidian 内部链接(基于 vault 根), 不受 md 所在目录影响
        rel = str(img_path.relative_to(media_dir().parent))
        return f"![[{rel}]]"

    img_dir.mkdir(parents=True, exist_ok=True)
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as hx:
            r = hx.get(url)
        if r.status_code == 200 and len(r.content) > 1024:
            img_path.write_bytes(r.content)
            # 用 Obsidian 内部链接(基于 vault 根), 不受 md 所在目录影响
            rel = str(img_path.relative_to(media_dir().parent))
            return f"![[{rel}]]"
    except Exception:
        pass
    # 退化: CDN URL（Feishu markdown 可直接渲染）
    return f"![{img_hash}]({url})"



# ── 时间格式化 ───────────────────────────────────────────────
_ts_cache = {}


def _today_start_ts() -> int:
    """今天 CST 00:00 的 unix timestamp (10 位整数秒).

    用于 tieba "今日 = 今天发的帖" 过滤: 跳过今日被回复但不是今日发
    的老帖 (首页活跃帖), 不入库也不显示.
    """
    cst = datetime.timezone(datetime.timedelta(hours=8))
    today = datetime.datetime.now(cst).date()
    return int(datetime.datetime.combine(today, datetime.time(0, 0), tzinfo=cst).timestamp())


def _fmt_time(unix_ts: int) -> str:
    if not unix_ts or not isinstance(unix_ts, int):
        return ""
    if unix_ts in _ts_cache:
        return _ts_cache[unix_ts]
    try:
        import datetime
        d = datetime.datetime.fromtimestamp(
            unix_ts, tz=datetime.timezone(datetime.timedelta(hours=8))
        )
        s = d.strftime("%Y-%m-%d %H:%M")
    except Exception:
        s = str(unix_ts)
    _ts_cache[unix_ts] = s
    return s

# ── 用户名 ──────────────────────────────────────────────────

def _user_name(user) -> str:
    if dataclasses.is_dataclass(user):
        for fname in ("name", "nickname", "user_name", "show_name"):
            v = getattr(user, fname, None)
            if v:
                return str(v)
        return str(user)
    return str(user)


# ── 单吧异步爬取 ─────────────────────────────────────────────

async def _crawl_forum_async(forum: str, pages: int = PAGES) -> list:
    """对单个贴吧异步抓取，返回 (title, md_path) 列表。
    文件名前缀使用帖子真实创建日期 (YYYYMMDD)，不再用爬取日期。"""
    results = []
    async with aiotieba.Client() as client:
        for pn in range(1, pages + 1):
            try:
                threads = await client.get_threads(forum, pn=pn)
            except Exception as e:
                print(f"    ⚠️  get_threads({forum}, pn={pn}) 失败: {e}")
                break

            if not threads:
                break

            threads = threads[:THREAD_LIMIT]
            today_start_ts = _today_start_ts()
            for thread in threads:
                # 2026-08-04: 仅抓今天 (CST 00:00 之后) 发的帖. 今日被回复但不是今日发
                # 的老帖 (首页活跃帖) 一律跳过, 不入库也不显示.
                if (thread.create_time or 0) < today_start_ts:
                    continue
                tid = thread.tid
                title = str(thread.title)[:80] if thread.title else f"帖{tid}"
                # 用帖子真实创建日期做文件名前缀
                post_date = datetime.datetime.fromtimestamp(thread.create_time).strftime("%Y%m%d")
                out_path = notes_dir() / "tieba" / forum / f"{post_date}_{slugify(title, 30)}.md"
                if out_path.exists():
                    results.append((f"{forum} · {title}", str(out_path), None))
                    continue

                # 拿第 1 页楼层（包含楼主+前排回复，够用）
                floors = []
                seen_floors = set()
                try:
                    posts = await client.get_posts(tid, pn=1)
                    for p in posts:
                        if p.floor in seen_floors:
                            continue
                        seen_floors.add(p.floor)
                        uname = _user_name(p.user)
                        body = _render_contents(p.contents)
                        if body:
                            floors.append((p.floor, uname, body, p.create_time or 0))
                except Exception as e:
                    print(f"    ⚠️  get_posts({tid}) 失败: {e}")

                forum_dir = notes_dir() / "tieba" / forum
                forum_dir.mkdir(parents=True, exist_ok=True)
                md = _build_md(forum, tid, thread, floors)
                out_path.write_text(md, encoding="utf-8")
                results.append((f"{forum} · {title}", str(out_path), None))
                print(f"    ✅ [{forum}] {title[:40]} ({len(floors)} 楼层)")
                await asyncio.sleep(0.3)

    return results


# ── Markdown ────────────────────────────────────────────────

def _build_md(forum: str, tid: int, thread, floors: list) -> str:
    title = str(thread.title) if thread.title else f"帖{tid}"
    post_url = f"https://tieba.baidu.com/p/{tid}"
    replies = getattr(thread, "reply_num", 0) or 0
    view_num = getattr(thread, "view_num", 0) or 0
    author = _user_name(thread.user) if thread.user else ""
    last_time = _fmt_time(getattr(thread, "last_time", 0) or 0)
    create_time = _fmt_time(getattr(thread, "create_time", 0) or 0)
    # 2026-07-22: 加 frontmatter 让 push_aggregated 能解析 (load_platform_items_from_notes
    # 会跳过 author='未知作者' 的 md). tieba 没 '博主' 概念, 用 forum 作 author,
    # 发布者单独存 tieba_user.
    create_yyyymmdd = ""
    ct = getattr(thread, "create_time", 0) or 0
    if ct:
        import datetime
        create_yyyymmdd = datetime.datetime.fromtimestamp(ct).strftime("%Y%m%d")


    floor_blocks = []
    for floor_num, uname, body, ts in sorted(floors, key=lambda x: x[0]):
        ts_str = _fmt_time(ts) if ts else ""
        floor_blocks.append(
            f"**{uname}** · 楼{floor_num}{f' · {ts_str}' if ts_str else ''}\n\n{body}\n"
        )
    body_md = "\n\n---\n\n".join(floor_blocks) if floor_blocks else "[无内容]"

    fm = (
        f"---\n"
        f"source: tieba_post\n"
        f'title: "{title}"\n'
        f'author: "{forum}"\n'
        f'tieba_forum: "{forum}"\n'
        f'tieba_user: "{author}"\n'
        f"tieba_replies: {replies}\n"
        f"tieba_views: {view_num}\n"
        f"publish_date: {create_yyyymmdd}\n"
        f"source_url: {post_url}\n"
        f"collected_at: {create_yyyymmdd}\n"
        f"tags:\n  - tieba\n  - 订阅\n"
        f"---\n\n"
    )
    return (
        f"{fm}"
        f"## {title}\n\n"
        f"📅 发布 {create_time} · 🔗 原文链接: {post_url}\n"
        f"📌 贴吧: **{forum}** · 👤 {author} · 💬 {replies}回复 · 👁 {view_num}浏览\n\n"
        f"{body_md}\n"
    )


# ── 同步入口 ────────────────────────────────────────────────

def crawl_batch(date_yymmdd=None, pages: int = PAGES):
    """搜索型入口 (pipeline/run.py:process_search 调用)。
    读飞书 Watchlist ## 贴吧吧名，异步爬取，写 notes/tieba/<forum>/。
    返回: [(title, md_path, None), ...]
    """
    try:
        forums = get_tieba_forums()
    except Exception as e:
        print(f"  [warn] 飞书贴吧吧名读取失败，用默认: {e}")
        forums = []
    forums = forums or DEFAULT_FORUMS
    if not forums:
        print("  ⚠️  无贴吧名，跳过")
        return []

    all_out = []
    for forum in forums:
        print(f"  📌 贴吧 [{forum}] 抓取 {pages} 页...")
        t0 = time.time()
        try:
            results = asyncio.run(_crawl_forum_async(forum, pages))
            print(f"    → {len(results)} 帖 (耗时 {time.time()-t0:.1f}s)")
            all_out.extend(results)
        except Exception as e:
            print(f"    ❌ [{forum}] 异常: {e}")
    print(f"  ✅ 贴吧完成: {len(all_out)} 个文件")
    return all_out


if __name__ == "__main__":
    for title, md, _ in crawl_batch():
        print(f"  {title} → {md}")
