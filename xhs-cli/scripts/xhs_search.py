#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/xhs_search.py — 小红书 on-demand keyword 搜索 (返回 chat, 不写 md)

跟 crawl 的差异:
  - crawl = batch + watchlist + 写 vault md (慢、稳、后台)
  - 这里  = on-demand + 输入关键字 + 渲染 markdown 给 chat 看 (快、即时)

依赖:
  - ~/.local/bin/xhs (xiaohongshu-cli v0.6.4, 已登录)
  - 不需要 credentials/xiaohongshu.txt (xhs CLI 自带)

用法:
  # 1. 搜索 + 表格
  python xhs_search.py search "咖啡" --limit 5

  # 2. 搜索 + 下载封面图 + 渲染带图表格
  python xhs_search.py search "咖啡" --limit 3 --render

  # 3. 读单篇详情 + 下载全部图片 + 渲染
  python xhs_search.py detail 69c13d8100000000210127cb \
      --xsec-token "ABrGFeEzcpnmVJtaVqPo7xcM_G5rIy_uE4t-j74OytbD0=" \
      --render --max-images 9

  # 4. 一条龙: 搜索 → 自动取前 N 条详情 → 全部带图渲染
  python xhs_search.py auto "codex免费试用一个月怎么支付教程" \
      --limit 2 --with-content --render

输出位置:
  默认: ~/Documents/agent_spaces/output/xhs_images/
  可改: --out-dir /path/to/dir

风控提醒:
  - xhs search 不撞验证码,放心批量
  - xhs read 单次 OK,但批量会触发滑块验证码(连续 4-5 条)
  - --with-content 模式默认限速:每条 read 之间 sleep 3s
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# ──────────── 常量 ────────────
XHS_BIN = Path.home() / ".local" / "bin" / "xhs"
DEFAULT_OUT_DIR = Path.home() / "Documents" / "agent_spaces" / "output" / "xhs_images"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
REFERER = "https://www.xiaohongshu.com/"


# ──────────── 底层调用 ────────────

def _run_xhs(args, timeout=60):
    """调 xhs CLI, 返回 JSON dict"""
    r = subprocess.run([str(XHS_BIN)] + args + ["--json"],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"xhs CLI failed (rc={r.returncode}): {r.stderr.strip() or r.stdout[:200]}")
    out = r.stdout.strip()
    if not out:
        raise RuntimeError(f"xhs CLI empty output (stderr={r.stderr.strip()[:200]})")
    # xhs --json 模式输出纯 JSON;若前面有 WARNING, 找第一个 "{"
    json_start = out.find("{")
    if json_start < 0:
        raise RuntimeError(f"xhs CLI no JSON in output: {out[:200]}")
    return json.loads(out[json_start:])


def search(keyword, limit=10, sort="general", page=1):
    """调 xhs search, 返回 items list (字典形式)
    
    Args:
        keyword: 搜索关键词
        limit: 最多返回几条
        sort: general / popular / latest
        page: 翻页(默认 1)
    
    Returns:
        list of dict (note_card + id + xsec_token)
    """
    data = _run_xhs(["search", keyword, "--sort", sort, "--page", str(page)])
    if not data.get("ok"):
        raise RuntimeError(f"xhs search 返回 ok=false: {data}")
    items = data.get("data", {}).get("items", [])
    return items[:limit]


def read_detail(note_id, xsec_token="", timeout=60):
    """调 xhs read, 返回 note_card dict
    
    Args:
        note_id: 笔记 ID
        xsec_token: 该笔记的安全 token (从 search 结果拿)
    """
    args = ["read", note_id]
    if xsec_token:
        args += ["--xsec-token", xsec_token]
    data = _run_xhs(args, timeout=timeout)
    if not data.get("ok"):
        raise RuntimeError(f"xhs read 返回 ok=false: {data}")
    items = data.get("data", {}).get("items", [])
    if not items:
        raise RuntimeError(f"xhs read 没拿到笔记: note_id={note_id}")
    return items[0].get("note_card", {})


# ──────────── 图片下载(带缓存 + 防盗链) ────────────

def _download_image(url, out_dir, force=False):
    """下载单张图, 返回本地绝对路径
    
    - SHA256(URL)[:16] 作为缓存键
    - 带 User-Agent + Referer 防盗链
    - 已存在则跳过(除非 force=True)
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    
    # 找现有同 hash 文件
    if not force:
        for ext in (".webp", ".jpg", ".jpeg", ".png", ".gif"):
            for p in out_dir.glob(f"{url_hash}_*{ext}"):
                return str(p)
    
    # 推断扩展名
    ext = ".webp"
    m = re.search(r"\.(jpg|jpeg|png|gif|webp)(\?|$|!)", url.lower())
    if m:
        ext = "." + m.group(1)
    
    out_path = out_dir / f"{url_hash}_{int(time.time())}{ext}"
    
    import urllib.request
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": REFERER,
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            out_path.write_bytes(resp.read())
        return str(out_path)
    except Exception as e:
        return f"(下载失败: {type(e).__name__}: {str(e)[:80]})"


# ──────────── Markdown 渲染 ────────────

def _fmt_int(v):
    """数字美化: '3921' → '3,921'"""
    try:
        return f"{int(v):,}"
    except Exception:
        return str(v or "-")


def _get_cover_url(note_card):
    """拿封面图 URL (优先 url_default)"""
    cover = note_card.get("cover") or {}
    return cover.get("url_default") or cover.get("url_pre") or ""


def _get_image_urls(note_card):
    """拿全部图片 URL 列表(从 image_list, 去重保序)"""
    seen = set()
    urls = []
    cover = _get_cover_url(note_card)
    if cover:
        seen.add(cover)
        urls.append(cover)
    for img in note_card.get("image_list", []):
        for info in img.get("info_list", []):
            u = info.get("url", "")
            if u and u not in seen:
                seen.add(u)
                urls.append(u)
                break  # 一个 image_list 项只取一张
    return urls


def _build_url(note_id, xsec_token=""):
    """构造笔记 URL(带 xsec_token 保留 session)
    
    - 标准 web URL: https://www.xiaohongshu.com/discovery/item/{note_id}
    - 带 token:  ?xsec_token={xsec_token}
    """
    if not note_id:
        return ""
    url = f"https://www.xiaohongshu.com/discovery/item/{note_id}"
    if xsec_token:
        url += f"?xsec_token={xsec_token}&xsec_source=pc_search"
    return url


def _fmt_pubtime(note_card):
    """发布时间显示"""
    cti = note_card.get("corner_tag_info") or []
    for tag in cti:
        if tag.get("type") == "publish_time":
            return tag.get("text", "")
    # fallback: ms timestamp
    ms = note_card.get("time") or note_card.get("last_update_time")
    if ms:
        try:
            from datetime import datetime, timezone, timedelta
            dt = datetime.fromtimestamp(ms / 1000, tz=timezone(timedelta(hours=8)))
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    return "-"


def render_table(items, render_images=False, out_dir=DEFAULT_OUT_DIR, max_images_per_row=4):
    """把搜索结果渲染成 markdown 表格(可选下载封面)"""
    lines = []
    lines.append(f"## 🔍 搜索结果(共 {len(items)} 条)")
    lines.append("")
    
    # 简短表格(带链接列)
    lines.append("| # | 标题 | 作者 | 👍 | ⭐ | 💬 | 链接 |")
    lines.append("|---|---|---|---|---|---|---|")
    for i, it in enumerate(items, 1):
        nc = it.get("note_card", {})
        ii = nc.get("interact_info", {})
        user = nc.get("user", {})
        note_id = it.get("id", "")
        xsec_token = it.get("xsec_token", "")
        url = _build_url(note_id, xsec_token)
        title = nc.get('display_title') or '(无标题)'
        # 标题做成可点击链接
        title_cell = f"[{title[:40]}]({url})" if url else title[:40]
        lines.append(
            f"| {i} | {title_cell} "
            f"| {user.get('nick_name') or user.get('nickname') or '-'} "
            f"| {_fmt_int(ii.get('liked_count'))} "
            f"| {_fmt_int(ii.get('collected_count'))} "
            f"| {_fmt_int(ii.get('comment_count'))} "
            f"| [直达]({url}) |" if url else
            f"| {i} | {title[:40]} "
            f"| {user.get('nick_name') or user.get('nickname') or '-'} "
            f"| {_fmt_int(ii.get('liked_count'))} "
            f"| {_fmt_int(ii.get('collected_count'))} "
            f"| {_fmt_int(ii.get('comment_count'))} "
            f"| - |"
        )
    
    # 末尾补充所有 URL(便于批量复制)
    lines.append("")
    lines.append("**🔗 全部 URL(可批量复制):**")
    lines.append("")
    for i, it in enumerate(items, 1):
        nc = it.get("note_card", {})
        note_id = it.get("id", "")
        xsec_token = it.get("xsec_token", "")
        url = _build_url(note_id, xsec_token)
        if url:
            title = nc.get('display_title') or '(无标题)'
            lines.append(f"{i}. {url}  " + chr(10) + f"   *{title[:60]}*")
    
    if render_images:
        lines.append("")
        lines.append("### 🖼️ 封面预览")
        lines.append("")
        for i, it in enumerate(items, 1):
            nc = it.get("note_card", {})
            url = _get_cover_url(nc)
            if not url:
                continue
            local = _download_image(url, out_dir)
            lines.append(f"**{i}. {nc.get('display_title','-')[:50]}**")
            lines.append("")
            lines.append(f"![cover]({local})")
            lines.append("")
    
    return "\n".join(lines)


def render_detail(note_card, note_id="", xsec_token="",
                  render_images=False, out_dir=DEFAULT_OUT_DIR, max_images=9):
    """把单条笔记详情渲染成完整 markdown(可选下载全部图片)"""
    user = note_card.get("user", {})
    ii = note_card.get("interact_info", {})
    title = note_card.get("title") or note_card.get("display_title") or "(无标题)"
    desc = note_card.get("desc", "")
    
    lines = []
    lines.append(f"## 📖 {title}")
    lines.append("")
    lines.append(f"- **作者:** {user.get('nick_name') or user.get('nickname') or '-'}")
    lines.append(f"- **发布时间:** {_fmt_pubtime(note_card)}")
    lines.append(f"- **互动:** {_fmt_int(ii.get('liked_count'))} 赞 / {_fmt_int(ii.get('collected_count'))} 收 / {_fmt_int(ii.get('comment_count'))} 评 / {_fmt_int(ii.get('share_count'))} 分享")
    if note_id:
        url = _build_url(note_id, xsec_token)
        lines.append(f"- **note_id:** `{note_id}`")
        if url:
            lines.append(f"- **🔗 直达链接:** {url}")
    lines.append("")
    
    # 话题标签
    tags = note_card.get("tag_list") or []
    if tags:
        tag_names = [t.get("name","") for t in tags if t.get("name")]
        if tag_names:
            lines.append(f"**🏷️ 话题:** {' '.join('#'+n for n in tag_names[:10])}")
            lines.append("")
    
    # 正文
    if desc:
        lines.append("### 📝 正文")
        lines.append("")
        lines.append(desc)
        lines.append("")
    
    # 图片
    image_urls = _get_image_urls(note_card)
    if image_urls:
        lines.append(f"### 🖼️ 图片(共 {len(image_urls)} 张)")
        lines.append("")
        if render_images:
            shown = image_urls[:max_images]
            for i, url in enumerate(shown, 1):
                local = _download_image(url, out_dir)
                lines.append(f"**图 {i}**")
                lines.append("")
                lines.append(f"![xhs-{i}]({local})")
                lines.append("")
            if len(image_urls) > max_images:
                lines.append(f"_… 还有 {len(image_urls) - max_images} 张未展示,本地缓存路径: `{out_dir}`_")
        else:
            for i, url in enumerate(image_urls[:max_images], 1):
                lines.append(f"- 图 {i}: {url}")
    
    return "\n".join(lines)


# ──────────── CLI 入口 ────────────

def main():
    p = argparse.ArgumentParser(
        description="小红书 on-demand 搜索 (返回 chat, 不写 md)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    
    # search 子命令
    ps = sub.add_parser("search", help="按关键字搜索,返回 markdown 表格")
    ps.add_argument("keyword", help="搜索关键词")
    ps.add_argument("--limit", type=int, default=10)
    ps.add_argument("--sort", default="general", choices=["general","popular","latest"])
    ps.add_argument("--page", type=int, default=1)
    ps.add_argument("--render", action="store_true", help="下载封面图到本地")
    ps.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    
    # detail 子命令
    pd = sub.add_parser("detail", help="读单条笔记详情(正文+图片)")
    pd.add_argument("note_id", help="笔记 ID")
    pd.add_argument("--xsec-token", default="", help="该笔记的安全 token")
    pd.add_argument("--render", action="store_true", help="下载全部图片到本地")
    pd.add_argument("--max-images", type=int, default=9, help="最多展示几张图")
    pd.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    
    # auto 子命令: search + 自动取 top N 详情
    pa = sub.add_parser("auto", help="一气呵成: 搜索 → 详情 → 全部带图")
    pa.add_argument("keyword", help="搜索关键词")
    pa.add_argument("--limit", type=int, default=3, help="自动取前几条详情")
    pa.add_argument("--sort", default="general", choices=["general","popular","latest"])
    pa.add_argument("--with-content", action="store_true", default=True, help="(默认 true) 拿每条详情")
    pa.add_argument("--no-content", dest="with_content", action="store_false")
    pa.add_argument("--render", action="store_true", default=True, help="(默认 true) 下载图")
    pa.add_argument("--no-render", dest="render", action="store_false")
    pa.add_argument("--max-images", type=int, default=6)
    pa.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    pa.add_argument("--sleep", type=float, default=3.0, help="每条 read 之间间隔秒数(防风控)")
    
    args = p.parse_args()
    out_dir = Path(args.out_dir)
    
    if args.cmd == "search":
        items = search(args.keyword, args.limit, args.sort, args.page)
        print(render_table(items, render_images=args.render, out_dir=out_dir))
    
    elif args.cmd == "detail":
        nc = read_detail(args.note_id, args.xsec_token)
        print(render_detail(nc, note_id=args.note_id, xsec_token=args.xsec_token,
                            render_images=args.render, out_dir=out_dir,
                            max_images=args.max_images))
    
    elif args.cmd == "auto":
        items = search(args.keyword, args.limit, args.sort)
        print(render_table(items, render_images=False, out_dir=out_dir))
        print()
        print("=" * 60)
        print()
        if args.with_content:
            for i, it in enumerate(items, 1):
                nc = it.get("note_card", {})
                note_id = it.get("id", "")
                token = it.get("xsec_token", "")
                print(f"--- 第 {i}/{len(items)} 条 ---")
                print()
                try:
                    detail = read_detail(note_id, token)
                    print(render_detail(detail, note_id=note_id, xsec_token=token,
                                        render_images=args.render, out_dir=out_dir,
                                        max_images=args.max_images))
                except Exception as e:
                    print(f"(读详情失败: {e})")
                print()
                if i < len(items):
                    time.sleep(args.sleep)


if __name__ == "__main__":
    main()
