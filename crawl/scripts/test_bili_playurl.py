#!/usr/bin/env python3
"""测试 Bilibili 公开视频下载 - 完整响应"""
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
    
    params = {
        "bvid": bvid,
        "cid": cid,
        "qn": 64,
        "fnval": 0,
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
        print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])

asyncio.run(test())
