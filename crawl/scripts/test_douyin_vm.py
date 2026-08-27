#!/usr/bin/env python3
"""最小化抖音爬取测试"""
import sys, os, json

# 加载配置
import yaml
config_path = "/home/ubuntu/.agents/skills/crawl/ingest-douyin/douyin_api/crawlers/douyin/web/config.yaml"
with open(config_path) as f:
    config = yaml.safe_load(f)

cookie = config["TokenManager"]["douyin"]["headers"]["Cookie"]

# 导入 httpx
import httpx

VAULT = "/home/ubuntu/webdav/steven_vault"
os.makedirs(f"{VAULT}/notes/douyin/poc_test", exist_ok=True)

# 测试视频 ID
aweme_id = "7329956157827616051"
print(f"测试抖音视频: {aweme_id}")

# 1. 获取视频详情
print("1. 获取视频详情...")
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Cookie": cookie,
    "Referer": "https://www.douyin.com/"
}

resp = httpx.get(
    f"https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id={aweme_id}&device_platform=webapp&aid=6383",
    headers=headers, timeout=15, follow_redirects=True
)
data = resp.json()
aweme_detail = data.get("aweme_detail", {})
if not aweme_detail:
    status_msg = data.get("status_msg", "")
    print(f"  失败: status_code={data.get('status_code')}, msg={status_msg}")
    sys.exit(1)

desc = aweme_detail.get("desc", "")
author = aweme_detail.get("author", {}).get("nickname", "")
print(f"  标题: {desc[:50]}")
print(f"  作者: {author}")

# 2. 生成 markdown（不做下载，因为下载需要 a_bogus 签名）
print("2. 生成 Markdown...")
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

（待转录）

## 正文

（待转录）
"""

out_file = f"{VAULT}/notes/douyin/poc_test/{aweme_id}.md"
with open(out_file, "w") as f:
    f.write(md_content)

print(f"  已保存: {out_file}")

# 3. 验证文件
with open(out_file) as f:
    content = f.read()
    print(f"  文件大小: {len(content)} bytes")
    print(f"  包含正文: {'（待转录）' in content}")

print("\n✅ 抖音爬取测试完成!")
print(f"  输出文件: {out_file}")
