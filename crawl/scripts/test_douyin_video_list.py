#!/usr/bin/env python3
"""获取用户视频列表，选择一个有标题的视频"""
import sys
sys.path.insert(0, "/home/ubuntu/.agents/skills/crawl/ingest-douyin/douyin_api/crawlers/douyin/web")

from urllib.parse import urlencode, quote
import httpx
import yaml
from abogus import ABogus

# 配置
config_path = "/home/ubuntu/.agents/skills/crawl/ingest-douyin/douyin_api/crawlers/douyin/web/config.yaml"
with open(config_path) as f:
    config = yaml.safe_load(f)

cookie = config["TokenManager"]["douyin"]["headers"]["Cookie"]

# 获取用户视频列表
user_sec_uid = ""  # 需要填入一个有效的 sec_uid
base_url = "https://www.douyin.com/aweme/v1/web/aweme/post/"
params = {
    "sec_user_id": user_sec_uid,
    "max_cursor": "0",
    "count": "10",
    "device_platform": "webapp",
    "aid": "6383",
    "channel": "channel_pc_web",
    "pc_client_type": "1",
    "version_code": "170400",
    "version_name": "17.4.0",
}

bogus = ABogus()
a_bogus = bogus.get_value(params)
signed_url = base_url + "?" + urlencode(params) + "&a_bogus=" + quote(a_bogus, safe='')

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Cookie": cookie,
    "Referer": "https://www.douyin.com/",
}

print("获取用户视频列表...")
resp = httpx.get(signed_url, headers=headers, timeout=15, follow_redirects=True)
data = resp.json()

aweme_list = data.get("aweme_list", [])
print(f"返回视频数: {len(aweme_list)}")

# 找第一个有标题的视频
for a in aweme_list:
    desc = a.get("desc", "")
    if desc:
        print(f"\n第一个有标题的视频:")
        print(f"  ID: {a.get('aweme_id')}")
        print(f"  标题: {desc[:50]}")
        print(f"  作者: {a.get('author', {}).get('nickname', '')}")
        break
else:
    print("所有视频都没有标题")
