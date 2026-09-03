#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetchers/xiaohongshu.py — 小红书单条链接抓取 (xhs-cli 后端)

参考 crawl-vm platforms/xiaohongshu/crawler.py (xiaohongshu-cli v0.6.4, subprocess)
返回统一契约: (title, author, md_path, images_dir)
图片下载到 images_dir (由主流程决定物化/上传)
"""
import asyncio
import json
import re
import subprocess
from pathlib import Path
from typing import Optional, Dict, List, Any
from urllib.parse import urlparse, parse_qs

from .base import async_download_url_to_file

# xhs CLI 入口 (复用 crawl-vm venv 内安装)
DEFAULT_XHS_BIN = "/home/ubuntu/.dsh/skills/crawl-vm/.venv/bin/xhs"
DEFAULT_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/120.0 Safari/537.36")


def extract_note_id(url: str) -> Optional[str]:
    """从小红书 URL 提取 note_id"""
    m = re.search(r'/(note|explore|discovery/item|item)/([0-9A-Za-z]+)', url)
    if m:
        return m.group(2)
    m2 = re.search(r'/([0-9a-f]{24})', url)
    return m2.group(1) if m2 else None


async def resolve_short_url(short_url: str) -> Optional[str]:
    """解析 xhslink.cn 短链 → 完整小红书 URL"""
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            ["curl", "-s", "-L", "-o", "/dev/null", "-w", "%{url_effective}",
             "--max-time", "20", "-A", DEFAULT_UA, short_url],
            capture_output=True, text=True, timeout=30)
        final_url = (proc.stdout or "").strip()
        if final_url and "xiaohongshu.com" in final_url:
            return final_url
    except Exception as e:
        print(f"    [xhs] resolve_short_url failed: {e}")
    return None


def _run_xhs_sync(args: List[str], timeout: int = 90) -> Dict[str, Any]:
    """同步调 xhs-cli, 返回 JSON dict"""
    try:
        proc = subprocess.run(
            [DEFAULT_XHS_BIN] + args + ["--json"],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"xhs CLI 超时 (>{timeout}s): {' '.join(args[:2])}")
    if proc.returncode != 0:
        raise RuntimeError(f"xhs CLI 退出码 {proc.returncode}: {proc.stderr[:200]}")
    stdout = proc.stdout.strip()
    idx = stdout.find("{")
    if idx == -1:
        raise RuntimeError(f"xhs CLI 无 JSON 输出: {stdout[:200]}")
    try:
        return json.loads(stdout[idx:])
    except json.JSONDecodeError as e:
        raise RuntimeError(f"xhs CLI JSON 解析失败: {stdout[idx:idx+200]}")


async def crawl(url: str, tmp_dir: str, config: dict) -> tuple:
    """抓取小红书单条笔记，生成 md。

    图文笔记: 图片下载到 images_dir, md 里 ![](images/xx)
    视频笔记: md 含 audio_url, 由主流程转录

    Returns:
        (title, author, md_path, images_dir)
    """
    note_id = extract_note_id(url)
    if not note_id:
        # xhslink 短链: 先解析跳转
        resolved = await resolve_short_url(url)
        if resolved:
            note_id = extract_note_id(resolved)
            url = resolved
    if not note_id:
        raise RuntimeError(f"无法从小红书 URL 提取 note_id: {url[:80]}")

    # 从 URL 提取 xsec_token (read 详情需要)
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    xsec_token = qs.get("xsec_token", [""])[0] or ""

    # 读取详情
    args = ["read", note_id]
    if xsec_token:
        args += ["--xsec-token", xsec_token]
    result = await asyncio.to_thread(_run_xhs_sync, args, 60)
    if not result.get("ok"):
        raise RuntimeError(
            f"XHS read failed: {result.get('error', {}).get('message', '')}")
    items = (result.get("data") or {}).get("items", [])
    if not items:
        raise RuntimeError(f"XHS read returned no items for {note_id}")
    note_card = items[0].get("note_card", {})

    info = _parse_note_info(note_card)
    title = info["title"] or note_id
    author = info["author"] or "未知作者"
    desc = info.get("desc", "")

    # 提取详情带 xsec_token 的 source_url
    source_url = url
    xsec = note_card.get("xsec_token", "")
    # 交互数据
    interact = note_card.get("interact_info", {}) or {}
    liked = interact.get("liked_count", "")
    collected = interact.get("collected_count", "")
    comments = interact.get("comment_count", "0")

    from datetime import datetime, timezone, timedelta
    TZ = timezone(timedelta(hours=8))
    time_ms = info.get("time") or 0
    if time_ms:
        publish_date = datetime.fromtimestamp(time_ms / 1000).strftime("%Y-%m-%d")
    else:
        publish_date = datetime.now(TZ).strftime("%Y-%m-%d")

    out_dir = Path(tmp_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    audio_url = _get_audio_url(note_card)
    image_urls = _get_image_urls(note_card) if not audio_url else []

    # 下载图片
    image_links = []
    for idx, img_url in enumerate(image_urls, 1):
        ext = "png"
        if ".jpg" in img_url.lower() or "image/jpeg" in img_url.lower():
            ext = "jpg"
        elif ".webp" in img_url.lower() or "_webp" in img_url.lower():
            ext = "webp"
        dest = images_dir / f"img_{idx:03d}.{ext}"
        ok = await async_download_url_to_file(
            img_url, dest, DEFAULT_UA, "https://www.xiaohongshu.com/")
        if ok and dest.exists() and dest.stat().st_size > 0:
            image_links.append(f"images/{dest.name}")
            print(f"      [{idx}/{len(image_urls)}] ✅ {dest.stat().st_size} bytes")

    # 生成 md
    md_path = out_dir / "note.md"
    fm = [
        "---",
        f'title: "{title}"',
        f"author: {author}",
        f"source_url: {source_url}",
        f"publish_date: {publish_date}",
        "category: xiaohongshu",
        f"note_id: {note_id}",
        f"likes: {liked}",
        f"comments: {comments}",
        f"favorites: {collected}",
    ]
    if audio_url:
        fm += [
            "transcript_pending: true",
            "transcript_available: false",
            f'audio_url: "{audio_url}"',
        ]
    # 话题标签
    tags = [t.get("name", "") for t in (info.get("tag_list", []) or [])
            if isinstance(t, dict) and t.get("name")]
    if tags:
        fm.append(f'tags: "{", ".join(tags)}"')
    fm += ["---", ""]

    body = f"# {title}\n\n"
    if desc:
        body += f"## 正文\n\n{desc}\n\n"
    if audio_url:
        body += "## 视频\n\n(待转录)\n"
    if image_links:
        body += "## 图片\n\n"
        for link in image_links:
            body += f"![]({link})\n"

    md_path.write_text("\n".join(fm) + body, encoding="utf-8")
    print(f"    → 写入 {md_path.name} (图文/视频)")

    return title, author, str(md_path), str(images_dir)


def _parse_note_info(note_card: Dict) -> Dict:
    """解析 note_card → 摘要字段"""
    user = note_card.get("user", {})
    interact = note_card.get("interact_info", {})
    return {
        "note_id": note_card.get("note_id") or note_card.get("id") or "",
        "title": note_card.get("display_title") or note_card.get("title", ""),
        "author": user.get("nickname", "") or user.get("nick_name", ""),
        "author_id": user.get("user_id", ""),
        "type": note_card.get("type", "normal"),
        "liked_count": interact.get("liked_count", ""),
        "collected_count": interact.get("collected_count", ""),
        "desc": note_card.get("desc", ""),
        "time": note_card.get("time", 0),
        "tag_list": note_card.get("tag_list", []),
    }


def _get_audio_url(note_card: Dict) -> Optional[str]:
    """从 note_card 提取视频 URL"""
    v = note_card.get("video", {})
    if not isinstance(v, dict):
        return None
    media = v.get("media", {})
    if not isinstance(media, dict):
        return None
    stream = media.get("stream", {})
    if not isinstance(stream, dict):
        return None
    for codec in ("h264", "h265", "av1"):
        arr = stream.get(codec, [])
        if isinstance(arr, list) and arr:
            item = arr[0]
            url = item.get("master_url") if isinstance(item, dict) else None
            if url:
                return url
            backup = item.get("backup_urls", []) if isinstance(item, dict) else []
            if isinstance(backup, list) and backup:
                return backup[0]
    return None


def _get_image_urls(note_card: Dict) -> List[str]:
    """从 note_card 提取图文图片 URL 列表"""
    urls = []
    for img in note_card.get("image_list", []):
        if isinstance(img, dict):
            info_list = img.get("info_list", [])
            if isinstance(info_list, list) and info_list:
                url = info_list[0].get("url", "")
                if url:
                    urls.append(url)
    return urls