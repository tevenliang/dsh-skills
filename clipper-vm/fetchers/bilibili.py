#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetchers/bilibili.py — B站单条链接抓取

参考 crawl-vm platforms/bilibili/crawler.py (WBI 签名 + mixin_key 重试)
返回统一契约: (title, author, md_path, images_dir)
"""
import asyncio
import hashlib
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from typing import Optional, Dict

import httpx


# WBI keys 模块路径 (Mac 同款)
WBI_KEYS_PATH = Path.home() / ".dsh" / "skills" / "crawl" / "ingest-douyin" / "douyin_api" / "crawlers" / "bilibili" / "web" / "wbi_keys.py"


def extract_bvid(url: str) -> Optional[str]:
    """从 B站 URL 提取 BV 号"""
    m = re.search(r'(BV[0-9A-Za-z]{10})', url)
    if m:
        return m.group(1)
    # b23.tv 短链通过主流程 resolve 后处理, 这里先返回 None
    return None


async def crawl(url: str, tmp_dir: str, config: dict) -> tuple:
    """抓取 B站视频详情，生成 md (transcript_pending: true + audio_url)。

    Returns:
        (title, author, md_path, images_dir)
    """
    bvid = extract_bvid(url)
    if not bvid:
        raise RuntimeError(f"无法从 URL 提取 BV 号: {url[:80]}")

    cookie_file = Path(config["platforms"]["bilibili"]["cookie_file"])
    cookie = cookie_file.read_text().strip()
    proxy = config.get("vm", {}).get("proxy", "http://127.0.0.1:7890")

    crawler = _BilibiliApi(cookie, proxy)
    detail = await crawler.fetch_video_detail(bvid)
    if not detail:
        return None, None, None, None

    title = detail.get("title", "")
    author = (detail.get("owner", {}) or {}).get("name", "")
    cid = detail.get("cid", 0)

    # 获取音频 URL
    audio_url = await crawler.get_playurl(bvid, cid)

    # 生成 md
    from datetime import datetime, timezone, timedelta
    TZ = timezone(timedelta(hours=8))
    pubdate = detail.get("pubdate", 0) or 0
    publish_iso = (datetime.fromtimestamp(pubdate, TZ).strftime("%Y-%m-%dT%H:%M:%S")
                   if pubdate else datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S"))

    out_dir = Path(tmp_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "note.md"

    # 视频封面
    pic = detail.get("pic", "") or ""

    fm = [
        "---",
        f'title: "{title}"',
        f"publish_time: {publish_iso}",
        "category: bilibili",
        f"source_url: {url}",
        f"uid: {bvid}",
        f"author: {author}",
        f"cid: {cid}",
        "transcript_pending: true",
        "transcript_available: false",
        f'audio_url: "{audio_url or ""}"',
        f'pic: "{pic}"',
        "created: " + datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S"),
        "---",
        "",
        f"## {title or bvid}",
        "",
    ]
    md_path.write_text("\n".join(fm), encoding="utf-8")
    print(f"    → 写入 {md_path.name} (元数据, 待转录)")

    return title or bvid, author, str(md_path), ""


class _BilibiliApi:
    """B站 Web API 封装 (精简自 crawl-vm, 仅保留单条详情能力)"""

    def __init__(self, cookie: str, proxy: str):
        self.cookie = cookie
        self.proxy = proxy

        sys.path.insert(0, str(WBI_KEYS_PATH.parent))
        from wbi_keys import fetch_mixin_key, get_cached_mixin_key
        self._fetch_mixin_key = fetch_mixin_key
        self._get_cached_mixin_key = get_cached_mixin_key

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Cookie": cookie,
            "Referer": "https://www.bilibili.com/",
        }

    def _calc_w_rid(self, params: dict) -> str:
        mixin_key = self._get_cached_mixin_key()
        if not mixin_key:
            asyncio.get_event_loop().run_until_complete(self._fetch_mixin_key())
            mixin_key = self._get_cached_mixin_key()
        if not mixin_key:
            raise RuntimeError("Failed to get mixin_key")

        params = dict(params)
        params['wts'] = str(int(time.time()))
        params = dict(sorted(params.items()))
        params = {k: ''.join(c for c in str(v) if c not in "!'()*") for k, v in params.items()}
        query = urlencode(params)
        return hashlib.md5((query + mixin_key).encode()).hexdigest()

    async def ensure_mixin_key(self):
        """确保 mixin_key 可用 (带退避重试)"""
        try:
            mixin_key = self._get_cached_mixin_key()
            if mixin_key:
                return
        except RuntimeError:
            pass
        last_err = None
        for attempt in range(1, 4):
            try:
                await self._fetch_mixin_key()
                return
            except Exception as e:
                last_err = e
                print(f"    [bili] mixin_key 拉取失败(第{attempt}次): {type(e).__name__}: {str(e)[:80]}")
                if attempt < 3:
                    await asyncio.sleep(2 * attempt)
        raise last_err if last_err else RuntimeError("mixin_key 获取失败")

    async def fetch_video_detail(self, bvid: str) -> Optional[Dict]:
        await self.ensure_mixin_key()
        async with httpx.AsyncClient(proxy=self.proxy, timeout=15, verify=False) as client:
            resp = await client.get(
                f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
                headers=self.headers
            )
            data = resp.json()
        if data.get("code") != 0:
            print(f"    [bilibili] fetch_video_detail failed: code={data.get('code')}, msg={data.get('message', '')}")
            return None
        return data.get("data", {})

    async def get_playurl(self, bvid: str, cid: int, qn: int = 64) -> Optional[str]:
        await self.ensure_mixin_key()
        params = {
            "bvid": bvid,
            "cid": cid,
            "qn": qn,
            "fnval": 16,
            "fnver": 0,
            "type": "mp4",
        }
        w_rid = self._calc_w_rid(params)
        params['w_rid'] = w_rid
        params['wts'] = str(int(time.time()))

        async with httpx.AsyncClient(proxy=self.proxy, timeout=15, verify=False) as client:
            resp = await client.get(
                "https://api.bilibili.com/x/player/playurl",
                headers=self.headers,
                params=params
            )
            data = resp.json()

        if data.get("code") != 0:
            print(f"    [bilibili] get_playurl failed: code={data.get('code')}, msg={data.get('message', '')}")
            return None

        d = data.get("data", {})
        dash = d.get("dash", {})
        if dash:
            audio_url = dash.get("audio", [{}])[0].get("baseUrl", "")
            if audio_url:
                return audio_url
        durl = d.get("durl", [])
        if durl:
            return durl[0].get("url", "")
        return None