#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
platforms/xiaohongshu/crawler.py — 小红书爬虫 (xhs-cli 后端)

Stack: xiaohongshu-cli (v0.6.4, subprocess 调用) — 与 Mac 端同款工具链

为什么用 xhs-cli 而不是裸 curl_cffi + xhshow:
  1. cookie 由 xhs-cli 管理: TTL 7 天自动从浏览器刷新, 响应 Set-Cookie 自动合并
  2. 签名算法内部维护 (sign_main_api), 不依赖社区版 xhshow 的稳定性
  3. 内置退避重试 + 滑块验证码冷却 (Http 461/471 → 指数退避)
  4. 扫码登录一次 → 60 天内不用换 cookie (浏览器真实会话)

对外接口 (与 DouyinCrawler/BilibiliCrawler 对齐):
  - get_user_notes(user_id, num)     → 用户笔记列表 (含 xsec_token)
  - get_note_detail(note_id, xsec_token) → 单笔记详情 (note_card)
  - get_homefeed(num)                → 首页推荐 (测试/探索)
  - search_notes(keyword, ...)       → 搜索
  - parse_note_info(note_card)       → 解析摘要字段
  - get_audio_url(note_card)         → 视频 URL
  - get_image_urls(note_card)        → 图文图片 URL 列表

注意:
  - 所有调用都是同步 subprocess (xhs-cli), 在 async 场景通过 asyncio.to_thread 包装
  - 必须先用 scripts/xhs_playwright_login.py 扫码登录 (生成 ~/.xiaohongshu-cli/cookies.json)
"""
import asyncio
import json
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any

# xhs CLI 入口 (crawl-vm venv 内)
DEFAULT_XHS_BIN = "/home/ubuntu/.dsh/skills/crawl-vm/.venv/bin/xhs"

# cookie 文件路径 (保留兼容, xhs-cli 自管但文件也同步写一份)
COOKIE_FILE = Path.home() / ".agents" / "credentials" / "ominicrawl" / "xiaohongshu.txt"
DEFAULT_PROXY = ""  # xhs-cli 直连, 不需要显式 proxy
DEFAULT_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/120.0 Safari/537.36")


def _run_xhs_sync(args: List[str], timeout: int = 90) -> Dict[str, Any]:
    """同步调 xhs-cli, 返回 JSON dict (内部含 ok/data 结构)"""
    try:
        proc = subprocess.run(
            [DEFAULT_XHS_BIN] + args + ["--json"],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"xhs CLI 超时 (>{timeout}s): {' '.join(args[:2])}")
    if proc.returncode != 0:
        raise RuntimeError(f"xhs CLI 退出码 {proc.returncode}: {proc.stderr[:200]}")

    # xhs CLI 输出可能有前置日志, 找第一个 "{" 开始解析
    stdout = proc.stdout.strip()
    idx = stdout.find("{")
    if idx == -1:
        raise RuntimeError(f"xhs CLI 无 JSON 输出: {stdout[:200]}")
    try:
        return json.loads(stdout[idx:])
    except json.JSONDecodeError as e:
        raise RuntimeError(f"xhs CLI JSON 解析失败: {stdout[idx:idx+200]}")


class XiaohongshuCrawler:
    """小红书爬虫 — xhs-cli 后端"""

    def __init__(self, cookie: str = "", proxy: str = DEFAULT_PROXY):
        # 兼容性保留参数: cookie 由 xhs-cli 管理, 传入也不使用
        self.cookie = cookie
        self.proxy = proxy
        self.headers_base = {"User-Agent": DEFAULT_UA}

    # ==================== async 包装 ====================

    async def _run_xhs(self, args: List[str], timeout: int = 90) -> Dict[str, Any]:
        return await asyncio.to_thread(_run_xhs_sync, args, timeout)

    # ==================== API 方法 ====================

    async def get_user_notes(self, user_id: str, num: int = 10) -> List[Dict]:
        """拿指定用户的笔记列表 (watchlist 用)

        Args:
            user_id: 小红书用户 ID
            num: 请求数量 (xhs-cli 内部取上限, 用 JSON 后截取)

        Returns:
            notes list, 每条 note_card dict (兼容旧接口)
        """
        # 测试 user-posts 返回 num 固定 30, 这里按需截取
        result = await self._run_xhs(["user-posts", str(user_id)], timeout=60)
        if not result.get("ok"):
            raise RuntimeError(
                f"XHS user-posted failed: {result.get('error', {}).get('code')} "
                f"{result.get('error', {}).get('message', '')}"
            )
        notes = (result.get("data") or {}).get("notes", [])
        if num and num < len(notes):
            notes = notes[:num]
        return notes

    async def get_homefeed(self, num: int = 10) -> List[Dict]:
        """首页推荐流 (测试/探索用)

        Returns:
            items list, 每条含 note_card
        """
        result = await self._run_xhs(["feed"], timeout=60)
        if not result.get("ok"):
            raise RuntimeError(
                f"XHS homefeed failed: {result.get('error', {}).get('code')} "
                f"{result.get('error', {}).get('message', '')}"
            )
        items = (result.get("data") or {}).get("items", [])
        if num and num < len(items):
            items = items[:num]
        return items

    async def get_note_detail(self, note_id: str, xsec_token: str = "") -> Dict:
        """拿单笔记详情 (note_card)

        Args:
            note_id: 笔记 ID
            xsec_token: 安全 token (从 get_user_notes 列表获取)

        Returns:
            note_card dict (与解析方法兼容)
        """
        args = ["read", str(note_id)]
        if xsec_token:
            args += ["--xsec-token", str(xsec_token)]
        result = await self._run_xhs(args, timeout=60)
        if not result.get("ok"):
            raise RuntimeError(
                f"XHS feed failed: {result.get('error', {}).get('code')} "
                f"{result.get('error', {}).get('message', '')}"
            )
        items = (result.get("data") or {}).get("items", [])
        if not items:
            raise RuntimeError(f"XHS read returned no items for {note_id}")
        return items[0].get("note_card", {})

    async def search_notes(self, keyword: str, page: int = 1, page_size: int = 10) -> List[Dict]:
        """搜索笔记"""
        args = ["search", str(keyword), "--page", str(page)]
        result = await self._run_xhs(args, timeout=60)
        if not result.get("ok"):
            raise RuntimeError(
                f"XHS search failed: {result.get('error', {}).get('code')} "
                f"{result.get('error', {}).get('message', '')}"
            )
        items = (result.get("data") or {}).get("items", [])
        # 提取 note_card
        cards = []
        for it in items:
            nc = it.get("note_card") or it if isinstance(it, dict) else {}
            if nc:
                cards.append(nc)
        if page_size and page_size < len(cards):
            cards = cards[:page_size]
        return cards

    # ==================== 解析方法 (与旧接口对齐) ====================

    def parse_note_info(self, note_card: Dict) -> Dict:
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
            "time": note_card.get("time", 0),          # Unix ms
            "time_normal": note_card.get("time_normal", ""),
            "tag_list": note_card.get("tag_list", []),  # 话题标签
        }

    def get_audio_url(self, note_card: Dict) -> Optional[str]:
        """从 note_card 提取视频 URL"""
        if note_card.get("type") != "video":
            # xhs-cli 里视频笔记 type 可能是 "video"
            if not note_card.get("video"):
                return None
        if note_card.get("type") != "video" and not note_card.get("video"):
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
                break
        return None

    def get_image_urls(self, note_card: Dict) -> List[str]:
        """从 note_card 提取图文图片 URL 列表"""
        if note_card.get("type") not in ("normal", "image"):
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

    # ==================== 内部工具 (兼容) ====================

    def _parse_cookies(self) -> Dict[str, str]:
        """兼容旧接口: 从 cookie 字符串解析 dict"""
        cookies = {}
        for part in self.cookie.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()
        return cookies


# ==================== 测试 ====================
async def test_crawler():
    """测试爬虫 (需要已扫码登录)"""
    crawler = XiaohongshuCrawler()

    print("=== get_user_notes ===")
    try:
        notes = await crawler.get_user_notes("5866293c82ec3912a575bb88", num=5)
        print(f"  got {len(notes)} notes")
        for n in notes[:3]:
            print(f"    - {n.get('note_id','?')[:18]}.. | {n.get('display_title','?')[:30]} | type={n.get('type')}")
    except Exception as e:
        print(f"  ❌ {e}")
        return

    print("\n=== get_note_detail ===")
    if notes:
        nid = notes[0].get("note_id")
        xtok = notes[0].get("xsec_token")
        try:
            detail = await crawler.get_note_detail(nid, xtok)
            info = crawler.parse_note_info(detail)
            print(f"  ✅ note: {info['title'][:40]}")
            print(f"  image_count: {len(crawler.get_image_urls(detail))}")
            print(f"  video: {'yes' if crawler.get_audio_url(detail) else 'no'}")
        except Exception as e:
            print(f"  ❌ {e}")


if __name__ == "__main__":
    asyncio.run(test_crawler())