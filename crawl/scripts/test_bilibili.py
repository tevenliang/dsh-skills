#!/usr/bin/env python3
"""测试 Bilibili API on VM"""
import httpx
import asyncio

BILI_COOKIE = open("/home/ubuntu/.agents/credentials/ominicrawl/bilibili.txt").read().strip()

async def test_bilibili():
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Cookie": BILI_COOKIE,
        "Referer": "https://www.bilibili.com/",
    }
    
    # 测试获取用户视频列表
    print("测试 B站 API...")
    
    # 方法1: 直接用 wbi 签名
    try:
        from pathlib import Path
        import sys
        sys.path.insert(0, "/home/ubuntu/.agents/skills/crawl/ingest-bilibili")
        
        from bilibili.wbi import BilibiliWbi
        
        cookie = BILI_COOKIE
        print(f"Cookie 长度: {len(cookie)}")
        
        async with BilibiliWbi(cookie=cookie) as bili:
            # 获取当前用户信息
            print("\n1. 获取 nav 信息...")
            nav = await bili._fetch_nav()
            print(f"   nav 响应: {str(nav)[:200]}")
            
            if nav.get("code") == 0:
                uname = nav.get("data", {}).get("uname", "N/A")
                print(f"   用户名: {uname}")
                
                # 获取用户视频
                print("\n2. 获取用户视频列表...")
                mid = nav.get("data", {}).get("mid", "")
                print(f"   mid: {mid}")
                
                videos = await bili.fetch_user_post_videos(mid=mid, pn=1, ps=5)
                print(f"   视频列表: {str(videos)[:300]}")
            else:
                print(f"   nav 失败: code={nav.get('code')}, msg={nav.get('message')}")
                
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()

asyncio.run(test_bilibili())
