#!/usr/bin/env python3
"""完整 B站 爬取 → 转录 → 放入 vault/inbox"""
import sys
import httpx
import asyncio
import hashlib
import time
import json
import subprocess
import tempfile
from urllib.parse import urlencode
from pathlib import Path
from datetime import datetime

sys.path.insert(0, "/home/ubuntu/.agents/skills/crawl/ingest-douyin/douyin_api")
from crawlers.bilibili.web.wbi_keys import fetch_mixin_key, get_cached_mixin_key

PROXY = "http://127.0.0.1:7890"
VAULT = Path("/home/ubuntu/webdav/steven_vault")
INBOX = VAULT / "00_inbox"
INBOX.mkdir(parents=True, exist_ok=True)

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

async def get_audio_url(bvid, cid):
    """获取音频 URL"""
    cookie = open("/home/ubuntu/.agents/credentials/ominicrawl/bilibili.txt").read().strip()
    await fetch_mixin_key()
    mixin_key = get_cached_mixin_key()
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Cookie": cookie,
        "Referer": "https://www.bilibili.com/",
    }
    
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
            audio_url = dash.get('audio', [{}])[0].get('baseUrl', '')
            video_url = dash.get('video', [{}])[0].get('baseUrl', '')
            return audio_url or video_url, d
        return None, data

async def get_video_info(bvid):
    """获取视频信息"""
    cookie = open("/home/ubuntu/.agents/credentials/ominicrawl/bilibili.txt").read().strip()
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Cookie": cookie,
        "Referer": "https://www.bilibili.com/",
    }
    
    async with httpx.AsyncClient(proxy=PROXY, timeout=15) as client:
        resp = await client.get(
            f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
            headers=headers
        )
        return resp.json()

async def main():
    # 测试视频
    bvid = "BV1xx411c7mu"
    
    print(f"处理 B站 视频: {bvid}")
    
    # 1. 获取视频信息
    print("\n[1] 获取视频信息...")
    info = await get_video_info(bvid)
    if info.get('code') != 0:
        print(f"  失败: {info.get('message')}")
        return
    
    data = info.get('data', {})
    title = data.get('title', '无标题')
    author = data.get('owner', {}).get('name', '未知作者')
    cid = data.get('cid', 0)
    print(f"  标题: {title}")
    print(f"  作者: {author}")
    print(f"  CID: {cid}")
    
    # 2. 获取音频 URL
    print("\n[2] 获取音频 URL...")
    audio_url, _ = await get_audio_url(bvid, cid)
    if not audio_url:
        print(f"  失败: 无音频 URL")
        return
    print(f"  audio_url: {audio_url[:60]}...")
    
    # 3. 下载音频
    print("\n[3] 下载音频...")
    with tempfile.TemporaryDirectory() as tmpdir:
        m4a_path = Path(tmpdir) / f"{bvid}.m4a"
        wav_path = Path(tmpdir) / f"{bvid}.wav"
        
        cookie = open("/home/ubuntu/.agents/credentials/ominicrawl/bilibili.txt").read().strip()
        curl_cmd = [
            "curl", "-s", "-L", "-o", str(m4a_path),
            "-A", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "-H", f"Referer: https://www.bilibili.com/",
            audio_url
        ]
        r = subprocess.run(curl_cmd, timeout=120)
        
        if m4a_path.exists():
            size = m4a_path.stat().st_size
            print(f"  下载完成: {size} bytes")
            
            if size > 10000:
                # 转换为 wav
                ffmpeg_cmd = [
                    "ffmpeg", "-y", "-i", str(m4a_path),
                    "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                    str(wav_path)
                ]
                r = subprocess.run(ffmpeg_cmd, capture_output=True, timeout=120)
                
                if wav_path.exists():
                    print(f"  转换成功: {wav_path.stat().st_size} bytes")
                    
                    # 4. 转录 (Groq)
                    print("\n[4] 转录中 (Groq)...")
                    groq_key = json.loads(open("/home/ubuntu/.agents/credentials/ominicrawl/groq.json").read())["api_key"]
                    
                    groq_cmd = [
                        "curl", "-s", "--proxy", PROXY,
                        "-X", "POST",
                        "https://api.groq.com/openai/v1/audio/transcriptions",
                        "-H", f"Authorization: Bearer {groq_key}",
                        "-F", "model=whisper-large-v3",
                        "-F", "language=zh",
                        "-F", f"file=@{wav_path}",
                        "-F", "response_format=text",
                    ]
                    
                    r = subprocess.run(groq_cmd, capture_output=True, text=True, timeout=180)
                    
                    transcript = ""
                    if r.returncode == 0 and r.stdout.strip():
                        try:
                            result = json.loads(r.stdout)
                            transcript = result.get("text", r.stdout.strip())
                        except:
                            transcript = r.stdout.strip()
                        print(f"  转录成功: {len(transcript)} 字符")
                    else:
                        print(f"  转录失败: {r.stderr[:100] if r.stderr else r.returncode}")
                else:
                    print(f"  转换失败")
            else:
                print(f"  文件过小")
        else:
            print(f"  下载失败")
        
        # 5. 写入 inbox
        print("\n[5] 写入 vault/inbox...")
        safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title[:30])
        date_str = datetime.now().strftime("%m%d")
        out_file = INBOX / f"{date_str}-{safe_title}.md"
        
        body_content = transcript if transcript else "（无转录内容）"
        
        md_content = f"""---
platform: bilibili
author: {author}
source_url: https://www.bilibili.com/video/{bvid}
publish_date: 
tags: []
---

# {title}

## 链接

- 原始链接: https://www.bilibili.com/video/{bvid}

## 摘要

{body_content[:500] if body_content else '（无内容）'}

## 正文

{body_content}
"""
        
        with open(out_file, "w") as f:
            f.write(md_content)
        
        print(f"  已写入: {out_file.name}")
        print(f"  文件大小: {len(md_content)} bytes")

    print("\n✅ 完成!")

asyncio.run(main())
