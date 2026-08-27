#!/usr/bin/env python3
"""完整抖音爬取测试 - 使用 a_bogus 签名"""
import sys, os
sys.path.insert(0, "/home/ubuntu/.agents/skills/crawl/ingest-douyin/douyin_api/crawlers/douyin/web")

from urllib.parse import urlencode, quote
import httpx
import yaml
from datetime import datetime
from pathlib import Path

from abogus import ABogus

# 配置
config_path = "/home/ubuntu/.agents/skills/crawl/ingest-douyin/douyin_api/crawlers/douyin/web/config.yaml"
with open(config_path) as f:
    config = yaml.safe_load(f)

cookie = config["TokenManager"]["douyin"]["headers"]["Cookie"]
VAULT = "/home/ubuntu/webdav/steven_vault"

# 测试视频 ID
aweme_id = "7329956157827616051"
print(f"测试抖音视频: {aweme_id}")

# 构造带 a_bogus 签名的请求
base_url = "https://www.douyin.com/aweme/v1/web/aweme/detail/"
params = {
    "aweme_id": aweme_id,
    "device_platform": "webapp",
    "aid": "6383",
    "channel": "channel_pc_web",
    "pc_client_type": "1",
    "version_code": "170400",
    "version_name": "17.4.0",
}

# 生成 a_bogus 签名
bogus = ABogus()
a_bogus = bogus.get_value(params)
signed_url = base_url + "?" + urlencode(params) + "&a_bogus=" + quote(a_bogus, safe='')

print(f"\n1. 生成签名 URL...")
print(f"   a_bogus: {a_bogus[:30]}...")

# 发送请求
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36",
    "Cookie": cookie,
    "Referer": "https://www.douyin.com/",
}

print(f"\n2. 请求视频详情...")
resp = httpx.get(signed_url, headers=headers, timeout=15, follow_redirects=True)
print(f"   Status: {resp.status_code}")

data = resp.json()
aweme_detail = data.get("aweme_detail", {})

if not aweme_detail:
    print(f"   失败: status_code={data.get('status_code')}, msg={data.get('status_msg', '')}")
    sys.exit(1)

# 提取信息
desc = aweme_detail.get("desc", "无标题")
author = aweme_detail.get("author", {}).get("nickname", "未知")
video_url = ""
play_addr = aweme_detail.get("video", {}).get("play_api", "")
if not play_addr:
    play_addr = aweme_detail.get("video", {}).get("url", "")

print(f"   标题: {desc[:50] if desc else '(空)'}")
print(f"   作者: {author}")

# 生成 markdown
print(f"\n3. 生成 Markdown...")
safe_name = desc[:30].replace("/", "-").replace("\\", "-") if desc else aweme_id
out_file = Path(VAULT) / "notes" / "douyin" / "poc_test" / f"{safe_name}.md"
out_file.parent.mkdir(parents=True, exist_ok=True)

md_content = f"""---
platform: douyin
author: {author}
source_url: https://www.douyin.com/video/{aweme_id}
publish_date: {datetime.now().strftime('%Y-%m-%d')}
tags: []
---

# {desc}

## 链接

- 原始链接: https://www.douyin.com/video/{aweme_id}

## 视频信息

- 作者: {author}
- 视频ID: {aweme_id}

## 摘要

（待转录）

## 正文

（待转录）
"""

with open(out_file, "w") as f:
    f.write(md_content)

print(f"   已保存: {out_file.name}")
print(f"   文件大小: {len(md_content)} bytes")

print("\n✅ 完整爬取流程测试成功!")
