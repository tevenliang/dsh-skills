#!/usr/bin/env python3
"""直接用 httpx 测试 Bilibili API"""
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
    """B站 WBI 签名"""
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
    
    # 获取 mixin_key
    await fetch_mixin_key()
    mixin_key = get_cached_mixin_key()
    print(f"mixin_key: {mixin_key[:20]}..." if mixin_key else "None")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Cookie": cookie,
        "Referer": "https://www.bilibili.com/",
    }
    
    print("\n1. 获取用户视频列表...")
    mid = 3546977052658531
    params = {
        "mid": mid,
        "ps": 5,
        "pn": 1,
        "order": "pubdate",
    }
    w_rid = calc_w_rid(params, mixin_key)
    params['w_rid'] = w_rid
    params['wts'] = str(int(time.time()))
    
    print(f"   w_rid: {w_rid}")
    
    async with httpx.AsyncClient(proxy=PROXY, timeout=15) as client:
        resp = await client.get(
            "https://api.bilibili.com/x/space/wbi/arc/search",
            headers=headers,
            params=params
        )
        data = resp.json()
        print(f"   code={data.get('code')}, msg={data.get('message', '')[:60]}")
        
        if data.get('code') == 0:
            vlist = data.get('data', {}).get('list', {}).get('vlist', [])
            print(f"   视频数: {len(vlist)}")
            for v in vlist[:3]:
                print(f"   - {v.get('title', 'N/A')[:40]} (BV={v.get('bvid', 'N/A')})")
                if 'cid' in v:
                    print(f"     cid={v['cid']}")
        else:
            print(f"   详情: {str(data)[:200]}")

asyncio.run(test())
