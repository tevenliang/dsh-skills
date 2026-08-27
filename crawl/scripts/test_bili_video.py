#!/usr/bin/env python3
"""测试 Bilibili 视频详情 API"""
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
    
    # 尝试获取视频详情 - 用一个公开视频 BV1GJ411X7dV
    bvid = "BV1GJ411X7dV"
    
    # 视频详情 API (不需要 WBI 签名)
    print("1. 获取视频详情...")
    async with httpx.AsyncClient(proxy=PROXY, timeout=15) as client:
        resp = await client.get(
            f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
            headers=headers
        )
        data = resp.json()
        print(f"   code={data.get('code')}, msg={data.get('message', '')}")
        if data.get('code') == 0:
            d = data.get('data', {})
            print(f"   title: {d.get('title', 'N/A')}")
            print(f"   author: {d.get('owner', {}).get('name', 'N/A')}")
            print(f"   cid: {d.get('cid')}")
        else:
            print(f"   详情: {str(data)[:200]}")
    
    # 获取播放链接
    print("\n2. 获取播放链接...")
    params = {
        "bvid": bvid,
        "cid": 0,  # 先用0试试
        "qn": 64,
    }
    w_rid = calc_w_rid(params, mixin_key)
    params['w_rid'] = w_rid
    params['wts'] = str(int(time.time()))
    
    resp = await client.get(
        "https://api.bilibili.com/x/player/playurl",
        headers=headers,
        params=params
    )
    data = resp.json()
    print(f"   code={data.get('code')}, msg={data.get('message', '')}")
    if data.get('code') == 0:
        print(f"   成功获取播放链接!")
        audio_url = data.get('data', {}).get('dash', {}).get('audio', [{}])[0].get('baseUrl', '')
        print(f"   audio_url: {audio_url[:80] if audio_url else 'N/A'}...")
    else:
        print(f"   详情: {str(data)[:200]}")

asyncio.run(test())
