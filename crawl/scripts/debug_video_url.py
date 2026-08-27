#!/usr/bin/env python3
"""检查视频 URL 结构"""
import sys
sys.path.insert(0, "/home/ubuntu/.agents/skills/crawl/ingest-douyin/douyin_api/crawlers/douyin/web")
sys.path.insert(0, "/home/ubuntu/.agents/skills/crawl")

from urllib.parse import urlencode, quote
import httpx
import yaml
import json

from abogus import ABogus

config_path = "/home/ubuntu/.agents/skills/crawl/ingest-douyin/douyin_api/crawlers/douyin/web/config.yaml"
with open(config_path) as f:
    config = yaml.safe_load(f)

cookie = config["TokenManager"]["douyin"]["headers"]["Cookie"]

aweme_id = "7673836885130661158"

def make_signed_url(url, params):
    bogus = ABogus()
    a_bogus = bogus.get_value(params)
    return url + "?" + urlencode(params) + "&a_bogus=" + quote(a_bogus, safe='')

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
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

resp = httpx.get(make_signed_url(detail_url, detail_params), headers=headers, timeout=15, follow_redirects=True)
data = resp.json()
aweme_detail = data.get("aweme_detail", {})

print("=== 视频信息 ===")
print(f"desc: {aweme_detail.get('desc', '')[:60]}")
print(f"duration: {aweme_detail.get('video', {}).get('duration', 0)}")

# 打印 video 字段的完整结构
video = aweme_detail.get("video", {})
print(f"\n=== video 字段 keys: {list(video.keys()) if isinstance(video, dict) else type(video)}")

# 找到所有可能的 URL
def find_urls(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            find_urls(v, prefix + "." + k)
    elif isinstance(obj, list) and len(obj) > 0:
        find_urls(obj[0], prefix + "[0]")
    elif isinstance(obj, str) and ("http" in obj or ".mp4" in obj or "douyinvod" in obj):
        print(f"  {prefix}: {obj[:100]}")

print("\n=== 找到的 URL ===")
find_urls(aweme_detail)
