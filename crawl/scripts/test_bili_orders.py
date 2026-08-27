#!/usr/bin/env python3
"""测试 Bilibili API 不同的 order 参数"""
import sys
import httpx
import asyncio
import hashlib
import time
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
    
    mid = 3546977052658531
    
    for order in ["pubdate", "click", "stow", "default"]:
        params = {
            "mid": mid,
            "ps": 5,
            "pn": 1,
            "order": order,
        }
        w_rid = calc_w_rid(params, mixin_key)
        params['w_rid'] = w_rid
        params['wts'] = str(int(time.time()))
        
        async with httpx.AsyncClient(proxy=PROXY, timeout=15) as client:
            resp = await client.get(
                "https://api.bilibili.com/x/space/wbi/arc/search",
                headers=headers,
                params=params
            )
            data = resp.json()
            vlist = data.get('data', {}).get('list', {}).get('vlist', [])
            print(f"order={order}: code={data.get('code')}, count={len(vlist)}")
            
            if vlist:
                for v in vlist[:2]:
                    print(f"  - {v.get('title','N/A')[:30]} BV={v.get('bvid')} cid={v.get('cid')}")
        
        await asyncio.sleep(1)

asyncio.run(test())
