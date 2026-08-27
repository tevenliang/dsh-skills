#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
platforms/bilibili/crawler.py — B站爬虫

使用 WBI 签名调用 B站 Web API
"""
import asyncio
import hashlib
import time
import sys
from pathlib import Path
from urllib.parse import urlencode
from typing import Optional, List, Dict

import httpx


# WBI keys 模块路径
WBI_KEYS_PATH = Path.home() / ".agents" / "skills" / "crawl" / "ingest-douyin" / "douyin_api" / "crawlers" / "bilibili" / "web" / "wbi_keys.py"


class BilibiliCrawler:
    """B站爬虫"""
    
    def __init__(self, cookie: str, proxy: str = "http://127.0.0.1:7890"):
        self.cookie = cookie
        self.proxy = proxy
        
        # 动态导入 wbi_keys
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
        """计算 WBI 签名"""
        # 确保有 mixin_key
        mixin_key = self._get_cached_mixin_key()
        if not mixin_key:
            # 重新获取
            asyncio.get_event_loop().run_until_complete(self._fetch_mixin_key())
            mixin_key = self._get_cached_mixin_key()
        
        if not mixin_key:
            raise RuntimeError("Failed to get mixin_key")
        
        # 添加 wts
        params = dict(params)
        params['wts'] = str(int(time.time()))
        
        # 按 key 排序
        params = dict(sorted(params.items()))
        
        # 过滤 !'()* 字符
        params = {
            k: ''.join(c for c in str(v) if c not in "!'()*")
            for k, v in params.items()
        }
        
        # URL encode
        query = urlencode(params)
        
        # MD5
        return hashlib.md5((query + mixin_key).encode()).hexdigest()
    
    async def _fetch_nav(self) -> dict:
        """获取 nav 信息（包含用户信息和 mixin_key）"""
        async with httpx.AsyncClient(proxy=self.proxy, timeout=15) as client:
            resp = await client.get(
                "https://api.bilibili.com/x/web-interface/nav",
                headers=self.headers
            )
            return resp.json()
    
    async def ensure_mixin_key(self):
        """确保 mixin_key 可用"""
        try:
            mixin_key = self._get_cached_mixin_key()
            if mixin_key:
                return
        except RuntimeError:
            pass
        await self._fetch_mixin_key()
    
    async def fetch_video_detail(self, bvid: str) -> Optional[Dict]:
        """获取视频详情
        
        Args:
            bvid: 视频 BV 号
            
        Returns:
            视频详情 dict
        """
        await self.ensure_mixin_key()
        
        async with httpx.AsyncClient(proxy=self.proxy, timeout=15) as client:
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
        """获取播放地址（音频）
        
        Args:
            bvid: 视频 BV 号
            cid: 视频 CID
            qn: 画质
            
        Returns:
            音频 URL
        """
        await self.ensure_mixin_key()
        
        params = {
            "bvid": bvid,
            "cid": cid,
            "qn": qn,
            "fnval": 16,  # DASH 格式
            "fnver": 0,
            "type": "mp4",
        }
        
        w_rid = self._calc_w_rid(params)
        params['w_rid'] = w_rid
        params['wts'] = str(int(time.time()))
        
        async with httpx.AsyncClient(proxy=self.proxy, timeout=15) as client:
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
        
        # 优先获取 DASH 格式的音频
        dash = d.get("dash", {})
        if dash:
            audio_url = dash.get("audio", [{}])[0].get("baseUrl", "")
            if audio_url:
                return audio_url
        
        # Fallback 到 mp4 格式
        durl = d.get("durl", [])
        if durl:
            return durl[0].get("url", "")
        
        return None
    
    async def get_user_videos(self, mid: int, pn: int = 1, ps: int = 30, order: str = "pubdate") -> List[Dict]:
        """获取用户视频列表
        
        Args:
            mid: 用户数字 ID
            pn: 页码
            ps: 每页数量
            order: 排序 (pubdate/click/stow/default)
            
        Returns:
            视频列表
        """
        await self.ensure_mixin_key()
        
        params = {
            "mid": mid,
            "pn": pn,
            "ps": ps,
            "order": order,
        }
        
        w_rid = self._calc_w_rid(params)
        params['w_rid'] = w_rid
        params['wts'] = str(int(time.time()))
        
        async with httpx.AsyncClient(proxy=self.proxy, timeout=15) as client:
            resp = await client.get(
                "https://api.bilibili.com/x/space/wbi/arc/search",
                headers=self.headers,
                params=params
            )
            data = resp.json()
        
        if data.get("code") != 0:
            print(f"    [bilibili] get_user_videos failed: code={data.get('code')}, msg={data.get('message', '')}")
            return []
        
        vlist = data.get("data", {}).get("list", {}).get("vlist", [])
        return vlist
    
    def parse_video_info(self, video_data: Dict) -> Dict:
        """解析视频信息（从 get_user_videos 返回的 vlist 项）"""
        return {
            "video_id": video_data.get("bvid", ""),
            "title": video_data.get("title", ""),
            "author": video_data.get("author", ""),
            "mid": video_data.get("mid", ""),
            "cid": video_data.get("cid", 0),
            "duration_s": video_data.get("length", "0"),
            "pubdate": video_data.get("pubdate", 0),
            "pic": video_data.get("pic", ""),
        }
    
    async def get_mid_from_nav(self) -> Optional[int]:
        """从 nav 获取当前用户的 mid"""
        nav = await self._fetch_nav()
        if nav.get("code") == 0:
            return nav.get("data", {}).get("mid")
        return None


async def test_crawler():
    """测试爬虫"""
    # 读取 cookie
    cookie_file = Path.home() / ".agents" / "credentials" / "ominicrawl" / "bilibili.txt"
    cookie = cookie_file.read_text().strip()
    
    crawler = BilibiliCrawler(cookie)
    
    # 测试获取视频详情
    print("Testing fetch_video_detail...")
    bvid = "BV1xx411c7mu"
    detail = await crawler.fetch_video_detail(bvid)
    if detail:
        print(f"  title: {detail.get('title')}")
        print(f"  author: {detail.get('owner', {}).get('name')}")
        print(f"  cid: {detail.get('cid')}")
        
        # 获取播放地址
        cid = detail.get("cid")
        audio_url = await crawler.get_playurl(bvid, cid)
        print(f"  audio_url: {audio_url[:50] if audio_url else 'N/A'}...")
    
    # 测试获取用户视频
    print("\nTesting get_user_videos...")
    videos = await crawler.get_user_videos(3546977052658531, ps=5)
    print(f"  Got {len(videos)} videos")
    for v in videos[:3]:
        print(f"  - {v.get('title')} (BV={v.get('bvid')})")
    
    # 测试获取 mid
    print("\nTesting get_mid_from_nav...")
    mid = await crawler.get_mid_from_nav()
    print(f"  mid: {mid}")


if __name__ == "__main__":
    asyncio.run(test_crawler())
