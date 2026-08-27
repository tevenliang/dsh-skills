#!/usr/bin/env python3
"""测试 Bilibili API using the existing web_crawler"""
import sys
from pathlib import Path

# 直接导入
sys.path.insert(0, "/home/ubuntu/.agents/skills/crawl/ingest-douyin/douyin_api")

import httpx
import asyncio

async def test():
    cookie = open("/home/ubuntu/.agents/credentials/ominicrawl/bilibili.txt").read().strip()
    
    print("1. 测试 nav...")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://api.bilibili.com/x/web-interface/nav",
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                "Cookie": cookie,
                "Referer": "https://www.bilibili.com/",
            }
        )
        nav = resp.json()
        print(f"   code={nav.get('code')}, isLogin={nav.get('data',{}).get('isLogin')}")
        if nav.get('code') == 0:
            print(f"   uname: {nav['data']['uname']}")
    
    # 测试获取视频详情 - 用一个已知的BV
    print("\n2. 测试视频详情...")
    # 先用 wbi_keys 签名
    from crawlers.bilibili.web.wbi_keys import get_cached_mixin_key, fetch_mixin_key
    await fetch_mixin_key()
    mixin_key = get_cached_mixin_key()
    print(f"   mixin_key: {mixin_key[:20]}..." if mixin_key else "   mixin_key: None")
    
    # 用 WebCrawler
    from crawlers.bilibili.web.web_crawler import BilibiliWebCrawler
    crawler = BilibiliWebCrawler()
    
    # 测试获取视频信息 (用BV1GJ411X7dV - 闻哥的一个视频)
    bvid = "BV1GJ411X7dV"
    print(f"\n3. 获取视频 {bvid}...")
    try:
        result = await crawler.fetch_one_video(bvid)
        res_code = result.get("code") if isinstance(result, dict) else str(type(result))
        print(f"   result code: {res_code}")
        if isinstance(result, dict) and result.get("code") == 0:
            data = result.get("data", {})
            title = data.get('title', 'N/A')
            author = data.get('owner', {}).get('name', 'N/A')
            print(f"   title: {title[:40]}")
            print(f"   author: {author}")
        else:
            print(f"   详情: {str(result)[:200]}")
    except Exception as e:
        print(f"   错误: {e}")

asyncio.run(test())
