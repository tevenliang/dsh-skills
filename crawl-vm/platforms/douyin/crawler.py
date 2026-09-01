#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
platforms/douyin/crawler.py — 抖音爬虫

使用 a_bogus 签名调用抖音 Web API
"""
import asyncio
import sys
import time
from pathlib import Path
from urllib.parse import urlencode, quote
from typing import Optional, List, Dict

import httpx


# a_bogus 签名模块路径
ABOGUS_PATH = Path.home() / ".dsh" / "skills" / "crawl" / "ingest-douyin" / "douyin_api" / "crawlers" / "douyin" / "web" / "abogus.py"


class DouyinCrawler:
    """抖音爬虫"""
    
    def __init__(self, cookie: str, proxy: str = "http://127.0.0.1:7890"):
        self.cookie = cookie
        self.proxy = proxy
        
        # 动态导入 a_bogus
        sys.path.insert(0, str(ABOGUS_PATH.parent))
        from abogus import ABogus
        self.abogus = ABogus()
        
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36",
            "Cookie": cookie,
            "Referer": "https://www.douyin.com/",
        }
    
    def _sign_url(self, url: str, params: dict) -> str:
        """使用 a_bogus 签名 URL"""
        a_bogus = self.abogus.get_value(params)
        return url + "?" + urlencode(params) + "&a_bogus=" + quote(a_bogus, safe='')
    
    async def fetch_video_detail(self, aweme_id: str) -> Optional[Dict]:
        """获取视频详情
        
        Args:
            aweme_id: 视频 ID
            
        Returns:
            视频详情 dict，失败返回 None
        """
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
        
        signed_url = self._sign_url(url, params)
        
        async with httpx.AsyncClient(proxy=self.proxy, timeout=15, follow_redirects=True) as client:
            resp = await client.get(signed_url, headers=self.headers)
            data = resp.json()
        
        aweme_detail = data.get("aweme_detail", {})
        if not aweme_detail:
            print(f"    [douyin] fetch_video_detail failed: code={data.get('status_code')}, msg={data.get('status_msg', '')}")
            return None
        
        return aweme_detail
    
    async def get_user_videos(self, sec_user_id: str = "", max_cursor: str = "0", count: int = 30,
                                  recent_days: int = 7, max_retry: int = 3) -> List[Dict]:
        """获取用户视频列表 (对齐 Mac 版 crawl common-flow/crawl.py _list_douyin_videos)

        Args:
            sec_user_id: 用户 sec_uid
            max_cursor: 分页游标
            count: 每页数量 (默认 30 — Mac 版 fetch_count=max(30, limit+10))
            recent_days: 只保留最近 N 天的视频; 0 = 不过滤 (补历史用)
            max_retry: 限流退避重试次数 (Mac 版 _backoff=(20,40,80) ×3)

        Returns:
            视频列表 — 不排序 (抖音接口本身按 create_time 倒序返回, 实测验证),
            已排除置顶 (is_top)。限流(403/aweme_list=None)时退避重试。
        """
        # Mac 版 2026-08-13 fix: 抖音反爬限流 (403 / aweme_list=None) 会静默漏掉新视频。
        # 限流是短时窗口, 退避后重试通常能拿回新鲜列表。
        _backoff = (20, 40, 80)
        _last_err = ""
        aweme_list = None
        for _att in range(1, max_retry + 1):
            try:
                url = "https://www.douyin.com/aweme/v1/web/aweme/post/"
                params = {
                    "sec_user_id": sec_user_id,
                    "max_cursor": max_cursor,
                    "count": count,
                    "device_platform": "webapp",
                    "aid": "6383",
                    "channel": "channel_pc_web",
                    "pc_client_type": "1",
                    "version_code": "170400",
                    "version_name": "17.4.0",
                }
                signed_url = self._sign_url(url, params)

                # Mac 版 2026-08-22: wait_for(30s) 防 SSL 握手永久挂死
                async with httpx.AsyncClient(proxy=self.proxy, timeout=15, follow_redirects=True) as client:
                    resp = await asyncio.wait_for(
                        client.get(signed_url, headers=self.headers), timeout=30)
                    data = resp.json()
            except asyncio.TimeoutError:
                _last_err = "请求超时(30s)"
                if _att < max_retry:
                    print(f"    [douyin] 请求超时(30s, 第{_att}次), {_backoff[_att-1]}s 后重试…")
                    await asyncio.sleep(_backoff[_att-1])
                    continue
                print(f"    [douyin] 请求超时(30s) 重试耗尽: {_last_err}")
                return []
            except Exception as e:
                _last_err = f"库直连异常: {type(e).__name__}: {str(e)[:100]}"
                if "403" in _last_err or "Forbidden" in _last_err:
                    print(f"    [douyin] 403/风控({_att}次), 跳过")
                    return []
                if _att < max_retry:
                    print(f"    [douyin] 限流/异常(第{_att}次), {_backoff[_att-1]}s 后重试…")
                    await asyncio.sleep(_backoff[_att-1])
                    continue
                print(f"    [douyin] 重试耗尽: {_last_err}")
                return []

            if not isinstance(data, dict):
                print(f"    [douyin] 非 dict 响应(第{_att}次), 跳过")
                return []
            if data.get("status_code") != 0:
                print(f"    [douyin] get_user_videos failed: {data.get('status_code')}")
                return []
            aweme_list = data.get("aweme_list")
            # status_code=0 + aweme_list=None 是典型限流签名 → 退避重试
            if aweme_list is None:
                _sc = data.get("status_code")
                _last_err = f"aweme_list=None, status_code={_sc}(风控/Cookie过期/限流)"
                if _att < max_retry:
                    print(f"    [douyin] 限流(status_code={_sc}, 第{_att}次), {_backoff[_att-1]}s 后重试…")
                    await asyncio.sleep(_backoff[_att-1])
                    continue
                print(f"    [douyin] 失败: {_last_err}")
                return []
            break  # 成功拿到列表

        if aweme_list is None:
            print(f"    [douyin] 未知限流: {_last_err}")
            return []

        # 对齐 Mac 版: 排除置顶 (is_top) + 7 天窗口过滤
        normal = [v for v in aweme_list if not v.get("is_top")]
        if recent_days > 0:
            import time as _t
            _cutoff = int(_t.time()) - recent_days * 86400
            filtered = [v for v in normal if v.get("create_time", 0) >= _cutoff]
            if len(filtered) != len(normal):
                print(f"    [douyin] {recent_days}天窗口过滤: 跳过 {len(normal) - len(filtered)} 条历史视频")
            return filtered
        return normal
    
    def get_audio_url(self, aweme_detail: Dict) -> Optional[str]:
        """从视频详情获取音频 URL
        
        优先使用 music.play_url，fallback 到 video 字段
        """
        # 尝试 music 字段
        music_info = aweme_detail.get("music", {})
        if isinstance(music_info, dict):
            play_url = music_info.get("play_url")
            if isinstance(play_url, dict):
                url_list = play_url.get("url_list", [])
                if url_list:
                    return url_list[0] if isinstance(url_list[0], str) else url_list[0].get("url", "")
            elif isinstance(play_url, str):
                return play_url
        
        # 尝试 video.play_addr
        video_info = aweme_detail.get("video", {})
        if isinstance(video_info, dict):
            play_addr = video_info.get("play_addr", {})
            if isinstance(play_addr, dict):
                url_list = play_addr.get("url_list", [])
                if url_list:
                    return url_list[0] if isinstance(url_list[0], str) else url_list[0].get("url", "")
            
            # 尝试 download_addr
            download_addr = video_info.get("download_addr", {})
            if isinstance(download_addr, dict):
                url_list = download_addr.get("url_list", [])
                if url_list:
                    return url_list[0] if isinstance(url_list[0], str) else url_list[0].get("url", "")
        
        return None
    
    def parse_video_info(self, aweme_detail: Dict) -> Dict:
        """解析视频信息"""
        video_id = aweme_detail.get("aweme_id", "") or ""
        desc = aweme_detail.get("desc", "") or ""
        # Douyin 视频 desc 为空时，用视频 ID 作为唯一标识（避免"无标题"乱码）
        title = desc if desc.strip() else video_id
        return {
            "video_id": video_id,
            "title": title,
            "author": aweme_detail.get("author", {}).get("nickname", "未知作者"),
            "author_id": aweme_detail.get("author", {}).get("sec_uid", ""),
            "duration_ms": aweme_detail.get("video", {}).get("duration", 0) or 0,
            "create_time": aweme_detail.get("create_time", 0) or 0,
        }
    
    async def resolve_short_url(self, short_url: str) -> Optional[str]:
        """解析抖音短链接
        
        Args:
            short_url: v.douyin.com/xxx 格式
            
        Returns:
            完整 URL 或 aweme_id
        """
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(short_url)
                # 从最终 URL 提取 aweme_id
                final_url = str(resp.url)
                import re
                m = re.search(r'/video/(\d+)', final_url)
                if m:
                    return m.group(1)
        except Exception as e:
            print(f"    [douyin] resolve_short_url failed: {e}")
        return None


async def test_crawler():
    """测试爬虫"""
    # 读取 cookie
    cookie_config = Path.home() / "skills" / "crawl" / "ingest-douyin" / "douyin_api" / "crawlers" / "douyin" / "web" / "config.yaml"
    import yaml
    config = yaml.safe_load(cookie_config.read_text())
    cookie = config["TokenManager"]["douyin"]["headers"]["Cookie"]
    
    crawler = DouyinCrawler(cookie)
    
    # 测试获取视频详情
    print("Testing fetch_video_detail...")
    aweme_id = "7673836885130661158"
    detail = await crawler.fetch_video_detail(aweme_id)
    if detail:
        info = crawler.parse_video_info(detail)
        print(f"  title: {info['title']}")
        print(f"  author: {info['author']}")
        
        audio_url = crawler.get_audio_url(detail)
        print(f"  audio_url: {audio_url[:50] if audio_url else 'N/A'}...")
    else:
        print("  Failed!")
    
    # 测试获取用户视频
    print("\nTesting get_user_videos...")
    videos = await crawler.get_user_videos()
    print(f"  Got {len(videos)} videos")
    
    # 测试解析短链接
    print("\nTesting resolve_short_url...")
    resolved = await crawler.resolve_short_url("https://v.douyin.com/HMYRudqikP0")
    print(f"  Resolved: {resolved}")


if __name__ == "__main__":
    asyncio.run(test_crawler())
