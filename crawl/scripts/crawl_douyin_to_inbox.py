#!/usr/bin/env python3
"""完整抖音爬取 → 转录 → 放入 vault/inbox (使用 Groq + VPN 代理)"""
import sys, os
sys.path.insert(0, "/home/ubuntu/.agents/skills/crawl/ingest-douyin/douyin_api/crawlers/douyin/web")
sys.path.insert(0, "/home/ubuntu/.agents/skills/crawl")

from urllib.parse import urlencode, quote
import httpx
import yaml
import json
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime

from abogus import ABogus

# 配置
SKILL_DIR = Path("/home/ubuntu/.agents/skills/crawl")
config_path = SKILL_DIR / "ingest-douyin/douyin_api/crawlers/douyin/web/config.yaml"
with open(config_path) as f:
    config = yaml.safe_load(f)

cookie = config["TokenManager"]["douyin"]["headers"]["Cookie"]
VAULT = Path("/home/ubuntu/webdav/steven_vault")
INBOX = VAULT / "00_inbox"
INBOX.mkdir(parents=True, exist_ok=True)

# VPN 代理
PROXY = "http://127.0.0.1:7890"

aweme_id = "7673836885130661158"
print(f"处理抖音视频: {aweme_id}")

# ── 1. 获取视频详情 ────────────────────────────────────────────
print("\n[1] 获取视频详情...")

def make_signed_url(url, params):
    bogus = ABogus()
    a_bogus = bogus.get_value(params)
    return url + "?" + urlencode(params) + "&a_bogus=" + quote(a_bogus, safe='')

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36",
    "Cookie": cookie,
    "Referer": "https://www.douyin.com/",
}

detail_url = "https://www.douyin.com/aweme/v1/web/aweme/detail/"
detail_params = {
    "aweme_id": aweme_id,
    "device_platform": "webapp",
    "aid": "6383",
    "pc_client_type": "1",
    "version_code": "170400",
    "version_name": "17.4.0",
}

Resp = httpx.get(make_signed_url(detail_url, detail_params), headers=headers, timeout=15, follow_redirects=True)
data = Resp.json()
aweme_detail = data.get("aweme_detail", {})

if not aweme_detail:
    print(f"  失败: {data.get('status_msg', 'no detail')}")
    sys.exit(1)

desc = aweme_detail.get("desc", "") or "无标题"
author = aweme_detail.get("author", {}).get("nickname", "未知作者")
print(f"  标题: {desc[:60]}")
print(f"  作者: {author}")

# ── 2. 获取音频 URL ────────────────────────────────────────────
print("\n[2] 获取音频...")

music_url = None
music_info = aweme_detail.get("music", {})
if isinstance(music_info, dict):
    play_url = music_info.get("play_url")
    if isinstance(play_url, dict):
        url_list = play_url.get("url_list", [])
        if url_list:
            music_url = url_list[0] if isinstance(url_list[0], str) else url_list[0].get("url", "")
    elif isinstance(play_url, str):
        music_url = play_url

print(f"  音乐音频: {music_url[:80] if music_url else 'N/A'}...")

# ── 3. 下载音频 ──────────────────────────────────────────────
print("\n[3] 下载音频...")

transcript = ""
with tempfile.TemporaryDirectory() as tmpdir:
    audio_path = Path(tmpdir) / f"{aweme_id}.mp3"
    wav_path = Path(tmpdir) / f"{aweme_id}.wav"
    
    if music_url:
        print(f"  下载到: {audio_path}")
        curl_cmd = [
            "curl", "-s", "-L", "-o", str(audio_path),
            "-A", headers["User-Agent"],
            "-H", f"Referer: https://www.douyin.com/",
            music_url
        ]
        r = subprocess.run(curl_cmd, timeout=120)
        
        if audio_path.exists():
            size = audio_path.stat().st_size
            print(f"  下载完成: {size} bytes")
            
            if size > 10000:
                print(f"  转换为 wav...")
                ffmpeg_cmd = [
                    "ffmpeg", "-y", "-i", str(audio_path),
                    "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                    str(wav_path)
                ]
                r = subprocess.run(ffmpeg_cmd, capture_output=True, timeout=120)
                
                if wav_path.exists() and wav_path.stat().st_size > 1000:
                    print(f"  转换成功: {wav_path.stat().st_size} bytes")
                    
                    # ── 4. 转录 (Groq + 代理) ───────────────────────────
                    print("\n[4] 转录中 (Groq + 代理)...")
                    
                    groq_key_file = Path.home() / ".agents/credentials/ominicrawl/groq.json"
                    if groq_key_file.exists():
                        try:
                            groq_key = json.loads(groq_key_file.read_text())["api_key"]
                            
                            print(f"  调用 Groq API (通过代理 {PROXY})...")
                            
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
                            
                            if r.returncode == 0 and r.stdout.strip():
                                try:
                                    result_data = json.loads(r.stdout)
                                    if "text" in result_data:
                                        transcript = result_data["text"]
                                        print(f"  转录成功: {len(transcript)} 字符")
                                    elif "error" in result_data:
                                        print(f"  转录错误: {result_data['error']}")
                                    else:
                                        transcript = r.stdout.strip()
                                        print(f"  转录成功: {len(transcript)} 字符")
                                except json.JSONDecodeError:
                                    # 直接返回文本
                                    transcript = r.stdout.strip()
                                    print(f"  转录成功: {len(transcript)} 字符")
                            else:
                                print(f"  转录失败: {r.stderr[:200] if r.stderr else r.returncode}")
                        except Exception as e:
                            print(f"  转录异常: {e}")
                    else:
                        print(f"  未找到 Groq key")
                else:
                    print(f"  转换失败")
            else:
                print(f"  文件过小")
        else:
            print(f"  下载失败")
    else:
        print(f"  无法获取音频URL")

    # ── 5. 写入 vault/inbox ───────────────────────────────────
    print("\n[5] 写入 vault/inbox...")
    
    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in desc[:30])
    date_str = datetime.now().strftime("%m%d")
    out_file = INBOX / f"{date_str}-{safe_title}.md"
    
    body_content = transcript if transcript else "（无转录内容）"
    
    md_content = f"""---
platform: douyin
author: {author}
source_url: https://www.douyin.com/video/{aweme_id}
publish_date: 
tags: []
---

# {desc}

## 链接

- 原始链接: https://www.douyin.com/video/{aweme_id}

## 摘要

{body_content[:500] if body_content else '（无内容）'}

## 正文

{body_content}
"""
    
    with open(out_file, "w") as f:
        f.write(md_content)
    
    print(f"  已写入: {out_file.name}")
    print(f"  文件大小: {len(md_content)} bytes")
    print(f"  转录长度: {len(transcript) if transcript else 0} 字符")

print("\n✅ 完成!")
