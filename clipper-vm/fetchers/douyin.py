#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetchers/douyin.py — 抖音单条链接抓取

参考 crawl-vm platforms/douyin/crawler.py (a_bogus 签名 + 403 退避重试)
返回统一契约: (title, author, md_path, images_dir)
"""
import asyncio
import re
import sys
from pathlib import Path
from urllib.parse import urlencode
from typing import Optional, Dict

import httpx


# a_bogus 签名模块路径 (Mac 同款)
ABOGUS_PATH = Path.home() / ".dsh" / "skills" / "crawl" / "ingest-douyin" / "douyin_api" / "crawlers" / "douyin" / "web"


def extract_aweme_id(url: str) -> Optional[str]:
    """从抖音 URL 提取 aweme_id"""
    m = re.search(r'/video/(\d+)', url)
    if m:
        return m.group(1)
    m2 = re.search(r'/(\d{15,20})', url)
    return m2.group(1) if m2 else None


async def resolve_short_url(short_url: str) -> Optional[str]:
    """解析 v.douyin.com 短链 → aweme_id"""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(short_url)
            final_url = str(resp.url)
            m = re.search(r'/video/(\d+)', final_url)
            if m:
                return m.group(1)
    except Exception as e:
        print(f"    [douyin] resolve_short_url failed: {e}")
    return None


async def crawl(url: str, tmp_dir: str, config: dict) -> tuple:
    """抓取抖音视频详情，生成 md (transcript_pending: true + audio_url)。

    Returns:
        (title, author, md_path, images_dir)
    """
    aweme_id = extract_aweme_id(url)
    clean_url = url
    if not aweme_id:
        # v.douyin.com 短链: 先解析跳转
        aweme_id = await resolve_short_url(url)
        if aweme_id:
            clean_url = f"https://www.douyin.com/video/{aweme_id}"
    if not aweme_id:
        raise RuntimeError(f"无法从 URL 提取 aweme_id: {url[:80]}")

    # 加载 cookie
    cookie_config_path = Path(config["platforms"]["douyin"]["cookie_config"])
    import yaml
    cookie_config = yaml.safe_load(cookie_config_path.read_text(encoding="utf-8"))
    cookie = cookie_config["TokenManager"]["douyin"]["headers"]["Cookie"]

    proxy = config.get("vm", {}).get("proxy", "http://127.0.0.1:7890")

    crawler = _DouyinApi(cookie, proxy)
    detail = await crawler.fetch_video_detail(aweme_id)
    if not detail:
        return None, None, None, None

    info = crawler.parse_video_info(detail)
    audio_url = crawler.get_audio_url(detail)

    # 生成 md (frontmatter + 元数据, transcript 待主流程填充)
    from datetime import datetime, timezone, timedelta
    from common.util import sanitize_filename
    TZ = timezone(timedelta(hours=8))
    create_time = info.get("create_time") or 0
    publish_iso = (datetime.fromtimestamp(create_time, TZ).strftime("%Y-%m-%dT%H:%M:%S")
                   if create_time else datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S"))

    out_dir = Path(tmp_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "note.md"

    desc = info["title"]
    if desc == str(aweme_id):
        desc = ""  # desc 为空时标题用了 aweme_id, md 里标题留空由主流程从转录提取

    fm = [
        "---",
        f'title: "{desc}"',
        f"publish_time: {publish_iso}",
        "category: douyin",
        f"source_url: {clean_url}",
        f"uid: {aweme_id}",
        f"author: {info['author']}",
        "transcript_pending: true",
        "transcript_available: false",
        f'audio_url: "{audio_url or ""}"',
        "created: " + datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S"),
        "---",
        "",
        f"## {desc or aweme_id}",
        "",
    ]
    md_path.write_text("\n".join(fm), encoding="utf-8")
    print(f"    → 写入 {md_path.name} (元数据, 待转录)")

    return desc or str(aweme_id), info["author"], str(md_path), ""


class _DouyinApi:
    """抖音 Web API 封装 (精简自 crawl-vm, 仅保留单条详情能力)"""

    def __init__(self, cookie: str, proxy: str):
        self.cookie = cookie
        self.proxy = proxy

        sys.path.insert(0, str(ABOGUS_PATH.parent.parent.parent))  # douyin_api/
        from crawlers.douyin.web.utils import BogusManager
        self._bogus = BogusManager

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2",
            "Cookie": cookie,
            "Referer": "https://www.douyin.com/",
        }
        self._bogus_ua = self.headers["User-Agent"]

    def _sign_url(self, url: str, params: dict) -> str:
        params_with_token = {**params, "msToken": ""}
        a_bogus = self._bogus.ab_model_2_endpoint(params_with_token, self._bogus_ua)
        return url + "?" + urlencode(params) + "&a_bogus=" + a_bogus

    async def fetch_video_detail(self, aweme_id: str) -> Optional[Dict]:
        """获取视频详情 (带退避重试)"""
        url = "https://www.douyin.com/aweme/v1/web/aweme/detail/"
        params = {
            "aweme_id": aweme_id,
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "pc_client_type": "1",
            "version_code": "170400",
            "version_name": "17.4.0",
        }

        _backoff = (5, 15, 30)
        for _att in range(1, 4):
            signed_url = self._sign_url(url, params)

            async with httpx.AsyncClient(proxy=self.proxy, timeout=15, follow_redirects=True) as client:
                resp = await client.get(signed_url, headers=self.headers)

                if resp.status_code == 403:
                    body = resp.text[:300] if resp.text else "empty"
                    if "Uifid Not Found" in body or "Argus" in body:
                        if _att < 3:
                            wait = _backoff[_att - 1]
                            print(f"    [douyin] 403 安全拦截({_att}/3), {wait}s 后重试…")
                            await asyncio.sleep(wait)
                            continue
                        print(f"    [douyin] 403 安全拦截, 重试耗尽")
                        return None
                    print(f"    [douyin] 403: {body[:100]}")
                    return None

                try:
                    data = resp.json()
                except Exception as e:
                    print(f"    [douyin] JSON 解析失败: {e}")
                    return None

            aweme_detail = data.get("aweme_detail", {})
            if aweme_detail:
                return aweme_detail
            print(f"    [douyin] aweme_detail 为空: {data.get('status_msg', '')}")
            return None

        return None

    def get_audio_url(self, aweme_detail: Dict) -> Optional[str]:
        """从视频详情获取音频 URL"""
        music_info = aweme_detail.get("music", {})
        if isinstance(music_info, dict):
            play_url = music_info.get("play_url")
            if isinstance(play_url, dict):
                url_list = play_url.get("url_list", [])
                if url_list:
                    return url_list[0] if isinstance(url_list[0], str) else url_list[0].get("url", "")
            elif isinstance(play_url, str):
                return play_url

        video_info = aweme_detail.get("video", {})
        if isinstance(video_info, dict):
            play_addr = video_info.get("play_addr", {})
            if isinstance(play_addr, dict):
                url_list = play_addr.get("url_list", [])
                if url_list:
                    return url_list[0] if isinstance(url_list[0], str) else url_list[0].get("url", "")
            download_addr = video_info.get("download_addr", {})
            if isinstance(download_addr, dict):
                url_list = download_addr.get("url_list", [])
                if url_list:
                    return url_list[0] if isinstance(url_list[0], str) else url_list[0].get("url", "")
        return None

    def parse_video_info(self, aweme_detail: Dict) -> Dict:
        video_id = aweme_detail.get("aweme_id", "") or ""
        desc = aweme_detail.get("desc", "") or ""
        title = desc if desc.strip() else video_id
        return {
            "video_id": video_id,
            "title": title,
            "author": aweme_detail.get("author", {}).get("nickname", "未知作者"),
            "author_id": aweme_detail.get("author", {}).get("sec_uid", ""),
            "duration_ms": aweme_detail.get("video", {}).get("duration", 0) or 0,
            "create_time": aweme_detail.get("create_time", 0) or 0,
        }