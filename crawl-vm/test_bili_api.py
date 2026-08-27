#!/usr/bin/env python3
"""Test Bilibili API directly"""
import sys
sys.path.insert(0, '/home/ubuntu/.dsh/skills/crawl-vm')

import asyncio
import httpx
from platforms.bilibili.crawler import BilibiliCrawler
from pathlib import Path

async def test():
    cookie_path = Path.home() / ".agents/credentials/ominicrawl/bilibili.txt"
    cookie = cookie_path.read_text().strip()
    
    crawler = BilibiliCrawler(cookie)
    
    # Test fetch_user_videos
    print("Testing fetch_user_videos for mid=3546977052658531...")
    # Test the raw API call
    import time
    import hashlib
    from urllib.parse import urlencode
    
    mid = "3546977052658531"
    params = {"mid": mid, "pn": 1, "ps": 30, "order": "pubdate"}
    
    # Get mixin_key
    from wbi_keys import fetch_mixin_key, get_cached_mixin_key
    await crawler._fetch_mixin_key()
    mixin_key = crawler._get_cached_mixin_key()
    print(f"Mixin key: {mixin_key[:20] if mixin_key else 'NONE'}...")
    
    # Calculate w_rid
    params['wts'] = str(int(time.time()))
    params_sorted = dict(sorted(params.items()))
    params_filtered = {k: ''.join(c for c in str(v) if c not in "!'()*") for k, v in params_sorted.items()}
    query = urlencode(params_filtered)
    w_rid = hashlib.md5((query + mixin_key).encode()).hexdigest()
    
    params['w_rid'] = w_rid
    
    print(f"Params: {params}")
    
    async with httpx.AsyncClient(proxy=crawler.proxy, timeout=15) as client:
        resp = await client.get(
            "https://api.bilibili.com/x/space/wbi/arc/search",
            headers=crawler.headers,
            params=params
        )
        data = resp.json()
    
    print(f"API Response code: {data.get('code')}")
    print(f"API Response message: {data.get('message')}")
    if data.get('code') == 0:
        vlist = data.get('data', {}).get('list', {}).get('vlist', [])
        print(f"Number of videos: {len(vlist)}")
        if vlist:
            print(f"First video: {vlist[0].get('title', 'N/A')}")
    
    # Check nav
    print("\nTesting fetch_nav...")
    nav = await crawler._fetch_nav()
    print(f"Nav code: {nav.get('code')}, msg: {nav.get('message')}")
    if nav.get('code') == 0:
        print(f"Username: {nav.get('data', {}).get('uname', 'N/A')}")

asyncio.run(test())
