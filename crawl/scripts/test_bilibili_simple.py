#!/usr/bin/env python3
"""简单测试 Bilibili API on VM"""
import httpx
import asyncio
import hashlib
import time
import json
from urllib.parse import urlencode

BILI_COOKIE = open("/home/ubuntu/.agents/credentials/ominicrawl/bilibili.txt").read().strip()

# WBI 签名相关
MIXIN_KEY = "7cd084941c3a434c859f4c5a280 HenI4a"

def getMixinKey(orig: str) -> str:
    """获取混合密钥"""
    table = "BV1rV4y1o7tF6qE8Bc5dX9sC3mZkPpNjU2GgHhKjLm="
    return bytes.maketrans(
        bytes.maketrans(b'5LtD6XHknYV1tJc8fR3qAeUsW7i0oZ9dM2cU4bS2gTkO', b'0123456789abcdefghijklmnopqrstuvwxyz'),
        bytes(table, 'utf-8')
    )

async def test_bilibili():
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Cookie": BILI_COOKIE,
        "Referer": "https://www.bilibili.com/",
    }
    
    print("测试 B站 API...")
    
    # 测试 nav API
    async with httpx.AsyncClient(timeout=15) as client:
        print("\n1. 获取 nav 信息...")
        resp = await client.get(
            "https://api.bilibili.com/x/web-interface/nav",
            headers=headers
        )
        data = resp.json()
        print(f"   code: {data.get('code')}")
        print(f"   msg: {data.get('message', '')}")
        
        if data.get('code') == 0:
            uname = data.get('data', {}).get('uname', 'N/A')
            print(f"   用户名: {uname}")
            mid = data.get('data', {}).get('mid', '')
            print(f"   mid: {mid}")
            
            # 测试获取用户视频
            print("\n2. 获取用户视频...")
            params = {
                'mid': mid,
                'ps': 5,
                'pn': 1,
            }
            # WBI 签名
            params['wts'] = int(time.time())
            params = dict(sorted(params.items()))
            query = urlencode(params)
            w_rid = hashlib.md5((query + MIXIN_KEY).encode()).hexdigest()
            params['w_rid'] = w_rid
            
            resp2 = await client.get(
                "https://api.bilibili.com/x/space/wbi/arc/search",
                headers=headers,
                params=params
            )
            data2 = resp2.json()
            print(f"   code: {data2.get('code')}")
            print(f"   msg: {data2.get('message', '')}")
            if data2.get('code') == 0:
                vlist = data2.get('data', {}).get('list', {}).get('vlist', [])
                print(f"   视频数: {len(vlist)}")
            else:
                print(f"   详情: {str(data2)[:200]}")
        else:
            print(f"   nav 详情: {str(data)[:300]}")

asyncio.run(test_bilibili())
