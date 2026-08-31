#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
platforms/xiaohongshu/crawler.py — 小红书爬虫

Stack: xhshow (纯 Python X-s 签名) + curl_cffi (chrome131 浏览器指纹)

关键 API:
- GET  /api/sns/web/v1/user_posted  → 用户笔记列表(含 xsec_token)
- POST /api/sns/web/v1/homefeed     → 首页推荐流
- POST /api/sns/web/v1/feed         → 单笔记详情(需 xsec_token)
- POST /api/sns/web/v1/search/notes → 搜索

视频 URL: video.media.stream.h264[0].master_url
图文 URL: image_list[0].info_list[0].url
"""
import asyncio
from pathlib import Path
from typing import Optional, List, Dict

from curl_cffi.requests import AsyncSession

# xhshow: 纯 Python X-s 签名库 (无需 Playwright)
from xhshow import Xhshow

# cookie 文件路径 (与 Douyin/Bilibili 一致)
COOKIE_FILE = Path.home() / ".agents" / "credentials" / "ominicrawl" / "xiaohongshu.txt"
DEFAULT_PROXY = "http://127.0.0.1:7890"
DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0.0.0 Safari/537.36")


class XiaohongshuCrawler:
    """小红书 Web API 爬虫

    API 鉴权: a1 + web_session + webId (必需)
    签名方案: xhshow (X-s/x-s-common/x-t 多重 header, 纯 Python 计算)
    浏览器指纹: curl_cffi chrome131

    与 DouyinCrawler/BilibiliCrawler 接口对齐:
    - get_user_notes(user_id, num)   → 同 get_user_videos()
    - get_homefeed(num)              → 首页推荐
    - get_note_detail(note_id, xsec_token) → 单笔记详情(fetch_video_detail 对应)
    - parse_note_info(note_card)     → 解析 note_card 字段
    - get_audio_url(note_card)       → 提取视频 URL (无音频流, 直接取 video)
    """

    BASE_URL = "https://edith.xiaohongshu.com"

    def __init__(self, cookie: str, proxy: str = DEFAULT_PROXY):
        self.cookie = cookie
        self.proxy = proxy
        self.xs_client = Xhshow()
        self.headers_base = {
            "User-Agent": DEFAULT_UA,
            "Cookie": cookie,
            "Origin": "https://www.xiaohongshu.com",
            "Referer": "https://www.xiaohongshu.com/",
        }

    def _url(self, uri: str) -> str:
        return self.BASE_URL + uri if uri.startswith("/") else f"{self.BASE_URL}/{uri}"

    def _referer_for(self, note_id: str, xsec_token: str) -> str:
        return (f"https://www.xiaohongshu.com/discovery/item/{note_id}"
                f"?xsec_token={xsec_token}&xsec_source=pc_web")

    @property
    def headers(self) -> Dict[str, str]:
        """与 DouyinCrawler/BilibiliCrawler 接口对齐: self.headers["User-Agent"]"""
        return self.headers_base

    # ==================== API 方法 ====================

    async def get_user_notes(self, user_id: str, num: int = 10) -> List[Dict]:
        """拿指定用户的笔记列表 (watchlist 用)

        返回列表中每条包含: note_id, xsec_token, display_title, type, interact_info, cover, user 等
        注意: 列表响应只有摘要, 正文在 get_note_detail() 中

        Args:
            user_id: 小红书用户 ID (不是 sec_uid, 是 user_id 数字串)
            num: 每页数量

        Returns:
            notes list, 每条是 note_card dict
        """
        uri = "/api/sns/web/v1/user_posted"
        params = {"num": num, "cursor": "", "user_id": user_id, "image_scenes": "FD_WM_WEBP"}
        h = self.xs_client.sign_headers_get(uri=uri, cookies=self._parse_cookies(), params=params)
        h.update(self.headers_base)

        async with AsyncSession(proxy=self.proxy, impersonate="chrome131") as s:
            r = await s.get(self._url(uri), params=params, headers=h, timeout=15)

        j = r.json()
        if j.get("code") != 0:
            raise RuntimeError(f"XHS user_posted failed: {j.get('code')} {j.get('msg')}")
        # data=None 说明该用户无公开笔记或账号异常, 返回空列表
        if j.get("data") is None:
            return []
        return j["data"].get("notes", [])

    async def get_homefeed(self, num: int = 10) -> List[Dict]:
        """拿首页推荐流 (测试/探索用)

        Returns:
            items list, 每条含 note_card + xsec_token
        """
        uri = "/api/sns/web/v1/homefeed"
        payload = {"cursor_score": "", "num": num, "refresh_type": 1, "note_index": 0}
        h = self.xs_client.sign_headers_post(uri=uri, cookies=self._parse_cookies(), payload=payload)
        h.update(self.headers_base)

        async with AsyncSession(proxy=self.proxy, impersonate="chrome131") as s:
            r = await s.post(self._url(uri), json=payload, headers=h, timeout=15)

        j = r.json()
        if j.get("code") != 0:
            raise RuntimeError(f"XHS homefeed failed: {j.get('code')} {j.get('msg')}")
        if j.get("data") is None:
            return []
        return j["data"].get("items", [])

    async def get_note_detail(self, note_id: str, xsec_token: str) -> Dict:
        """拿单笔记详情 (需要 xsec_token)

        xsec_token 从 get_user_notes() 或 get_homefeed() 返回的条目中获取.

        Returns:
            note_card dict, 包含 desc/title/image_list/video/interact_info/user 等完整字段
        """
        uri = "/api/sns/web/v1/feed"
        payload = {
            "source_note_id": note_id,
            "image_scenes": ["FD_WM_WEBP"],
            "xsec_token": xsec_token,
        }
        h = self.xs_client.sign_headers_post(uri=uri, cookies=self._parse_cookies(), payload=payload)
        # Referer 必须带 xsec_token, 否则 406
        h["Referer"] = self._referer_for(note_id, xsec_token)
        # 保留其他 base headers (覆盖 Referer 以外的)
        for k, v in self.headers_base.items():
            if k != "Referer":
                h.setdefault(k, v)

        async with AsyncSession(proxy=self.proxy, impersonate="chrome131") as s:
            r = await s.post(self._url(uri), json=payload, headers=h, timeout=15)

        j = r.json()
        if j.get("code") != 0:
            raise RuntimeError(f"XHS feed failed: {j.get('code')} {j.get('msg')}")
        if j.get("data") is None:
            raise RuntimeError(f"XHS feed returned no data for {note_id}")
        items = j["data"].get("items", [])
        if not items:
            raise RuntimeError(f"XHS feed returned no items for {note_id}")
        return items[0].get("note_card", {})

    async def search_notes(self, keyword: str, page: int = 1, page_size: int = 10) -> List[Dict]:
        """搜索笔记"""
        uri = "/api/sns/web/v1/search/notes"
        payload = {"keyword": keyword, "page": page, "page_size": page_size,
                   "sort": "general", "search_id": ""}
        h = self.xs_client.sign_headers_post(uri=uri, cookies=self._parse_cookies(), payload=payload)
        h.update(self.headers_base)

        async with AsyncSession(proxy=self.proxy, impersonate="chrome131") as s:
            r = await s.post(self._url(uri), json=payload, headers=h, timeout=15)

        j = r.json()
        if j.get("code") != 0:
            raise RuntimeError(f"XHS search failed: {j.get('code')} {j.get('msg')}")
        if j.get("data") is None:
            return []
        return j["data"].get("items", [])

    # ==================== 解析方法 (与 Douyin/Bilibili 接口对齐) ====================

    def parse_note_info(self, note_card: Dict) -> Dict:
        """解析 note_card 字段, 提取关键信息

        对齐 DouyinCrawler.parse_video_info() 和 BilibiliCrawler.parse_video_info() 的返回格式.

        Returns:
            dict: {
                "note_id": str,
                "title": str,        # display_title 或 title
                "author": str,       # nickname
                "author_id": str,    # user_id
                "type": str,         # "video" | "normal"
                "liked_count": str,
                "collected_count": str,
                "desc": str,
            }
        """
        user = note_card.get("user", {})
        interact = note_card.get("interact_info", {})
        return {
            "note_id": note_card.get("note_id") or "",
            "title": note_card.get("display_title") or note_card.get("title", ""),
            "author": user.get("nickname", "") or user.get("nick_name", ""),
            "author_id": user.get("user_id", ""),
            "type": note_card.get("type", "normal"),
            "liked_count": interact.get("liked_count", ""),
            "collected_count": interact.get("collected_count", ""),
            "desc": note_card.get("desc", ""),
            # XHS 特有字段
            "time": note_card.get("time", 0),          # Unix ms
            "time_normal": note_card.get("time_normal", ""),
            "tag_list": note_card.get("tag_list", []),  # 话题标签
        }

    def get_audio_url(self, note_card: Dict) -> Optional[str]:
        """从 note_card 提取视频 URL

        XHS 的"音频"实际上是视频流(mp4), 没有独立的 audio track.
        优先取 h264 master_url, fallback 到 backup_urls[0].

        Returns:
            视频 mp4 URL, 无视频则返回 None
        """
        if note_card.get("type") != "video":
            return None

        v = note_card.get("video", {})
        if not isinstance(v, dict):
            return None

        media = v.get("media", {})
        if not isinstance(media, dict):
            return None

        stream = media.get("stream", {})
        if not isinstance(stream, dict):
            return None

        # 优先 h264
        for codec in ("h264", "h265", "av1"):
            arr = stream.get(codec, [])
            if isinstance(arr, list) and arr:
                item = arr[0]
                url = item.get("master_url") if isinstance(item, dict) else None
                if url:
                    return url
                # fallback to backup
                backup = item.get("backup_urls", []) if isinstance(item, dict) else []
                if isinstance(backup, list) and backup:
                    return backup[0]
                break

        return None

    def get_image_urls(self, note_card: Dict) -> List[str]:
        """从 note_card 提取图文图片 URL 列表

        Returns:
            URL 列表, 每项是图片直链
        """
        if note_card.get("type") != "normal":
            return []

        urls = []
        for img in note_card.get("image_list", []):
            if isinstance(img, dict):
                info_list = img.get("info_list", [])
                if isinstance(info_list, list) and info_list:
                    url = info_list[0].get("url", "")
                    if url:
                        urls.append(url)
        return urls

    # ==================== 内部工具 ====================

    def _parse_cookies(self) -> Dict[str, str]:
        """从 cookie 字符串解析出 dict"""
        cookies = {}
        for part in self.cookie.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()
        return cookies


# ==================== 测试 ====================
async def test_crawler():
    """测试爬虫"""
    cookie_file = COOKIE_FILE
    if not cookie_file.exists():
        print(f"Cookie 文件不存在: {cookie_file}")
        print("请先确保 cookie 已保存到该路径")
        return

    cookie = cookie_file.read_text().strip()
    crawler = XiaohongshuCrawler(cookie)

    # 测试 get_user_notes
    print("=== get_user_notes ===")
    # 先从 homefeed 拿一个有效的 user_id
    print("fetching homefeed to get a user_id...")
    items = await crawler.get_homefeed(num=5)
    print(f"  homefeed got {len(items)} items")

    for it in items[:2]:
        nc = it.get("note_card", {})
        uid = nc.get("user", {}).get("user_id", "")
        if uid:
            notes = await crawler.get_user_notes(uid, num=3)
            print(f"  user {uid[:16]}... has {len(notes)} notes")
            for n in notes[:2]:
                print(f"    - {n.get('note_id','?')[:16]}... | {n.get('display_title','?')[:30]} | {n.get('type')}")
            break

    # 测试拿一条笔记详情
    print("\n=== get_note_detail ===")
    if items:
        note_id = items[0]["id"]
        xsec = items[0].get("xsec_token", "")
        nc = await crawler.get_note_detail(note_id, xsec)
        info = crawler.parse_note_info(nc)
        print(f"  note_id: {info['note_id'][:16]}...")
        print(f"  title: {info['title'][:40]}")
        print(f"  author: {info['author']}")
        print(f"  type: {info['type']}")

        audio_url = crawler.get_audio_url(nc)
        if audio_url:
            print(f"  audio_url: {audio_url[:60]}...")
        else:
            print(f"  audio_url: (no video)")


if __name__ == "__main__":
    asyncio.run(test_crawler())
