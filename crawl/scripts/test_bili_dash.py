#!/usr/bin/env python3
"""测试 Bilibili DASH 格式 (音视频分离)"""
import sys
import httpx
import asyncio
import hashlib
import time
import json
from urllib.parse import urlencode

sys.path.insert(0, "/home/ubuntu/.agents/skills/crawl/ingest-douyin/douyin_api")
from crawlers.bilibili.web.wbi_keys import fetch_mixin_key, get_cached_mixin_key

PROXY = "http://127.0.0.1:7890"

def calc_w_rid(params, mixin_key):
    params = dict(params)
    params['wts'] = str(int(time.time()))
    params = dict(sorted(params.items()))
    params = {
        k: ''.join(c for c in str(v) if c not in "!'()*")
        for k, v in params.items()
    }
    query = urlencode(params)
    return hashlib.md5((query + mixin_key).encode()).hexdigest()

async def test():
    cookie = open("/home/ubuntu/.agents/credentials/ominicrawl/bilibili.txt").read().strip()
    
    await fetch_mixin_key()
    mixin_key = get_cached_mixin_key()
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Cookie": cookie,
        "Referer": "https://www.bilibili.com/",
    }
    
    bvid = "BV1xx411c7mu"
    cid = 3635863
    
    # 使用 fnval=16 获取 DASH 格式
    params = {
        "bvid": bvid,
        "cid": cid,
        "qn": 64,
        "fnval": 16,
        "fnver": 0,
        "type": "mp4",
    }
    w_rid = calc_w_rid(params, mixin_key)
    params['w_rid'] = w_rid
    params['wts'] = str(int(time.time()))
    
    async with httpx.AsyncClient(proxy=PROXY, timeout=15) as client:
        resp = await client.get(
            "https://api.bilibili.com/x/player/playurl",
            headers=headers,
            params=params
        )
        data = resp.json()
        
        if data.get('code') == 0:
            d = data.get('data', {})
            dash = d.get('dash', {})
            
            print("DASH 格式:")
            video_url = dash.get('video', [{}])[0].get('baseUrl', '')
            audio_url = dash.get('audio', [{}])[0].get('baseUrl', '')
            print(f"  video_url: {video_url[:80]}..." if video_url else "  video_url: N/A")
            print(f"  audio_url: {audio_url[:80]}..." if audio_url else "  audio_url: N/A")
            
            # 旧版格式
            durl = d.get('durl', [])
            if durl:
                print(f"\n旧版 mp4 格式:")
                print(f"  url: {durl[0].get('url', '')[:80]}...")
        else:
            print(f"code={data.get('code')}, msg={data.get('message', '')}")

asyncio.run(test())
