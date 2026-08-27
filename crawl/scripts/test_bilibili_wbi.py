#!/usr/bin/env python3
"""测试 Bilibili WBI on VM"""
import sys, asyncio
from pathlib import Path

DOUYIN_API = "/home/ubuntu/.agents/skills/crawl/ingest-douyin/douyin_api/crawlers/bilibili/web"
sys.path.insert(0, DOUYIN_API)

from wbi_keys import fetch_mixin_key, get_cached_mixin_key
import wbi as bili_wbi_module
BilibiliWbi = bili_wbi_module.BilibiliWbi

BILI_COOKIE = open("/home/ubuntu/.agents/credentials/ominicrawl/bilibili.txt").read().strip()

async def test():
    print("1. Fetching mixin_key...")
    await fetch_mixin_key()
    key = get_cached_mixin_key()
    print(f"   mixin_key: {key[:30]}..." if key else "   mixin_key: None")

    print("\n2. Testing BilibiliWbi...")
    async with BilibiliWbi(cookie=BILI_COOKIE) as bili:
        # 获取闻哥的视频
        mid = 3546977052658531
        print(f"   获取用户 {mid} 的视频列表...")
        videos = await bili.fetch_user_post_videos(mid=mid, pn=1, ps=5)
        print(f"   结果: code={videos.get('code')}, msg={videos.get('message', '')[:80]}")
        if videos.get('code') == 0:
            vlist = videos.get('data', {}).get('list', {}).get('vlist', [])
            print(f"   视频数: {len(vlist)}")
            for v in vlist[:3]:
                print(f"   - {v.get('title', 'N/A')[:40]} (BV={v.get('bvid', 'N/A')})")
        else:
            print(f"   错误详情: {str(videos)[:200]}")

asyncio.run(test())
