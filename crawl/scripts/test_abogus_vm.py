#!/usr/bin/env python3
import sys
sys.path.insert(0, "/home/ubuntu/.agents/skills/crawl/ingest-douyin/douyin_api/crawlers/douyin/web")

from urllib.parse import urlencode, quote
from abogus import ABogus

# 原始 URL
url_str = "https://www.douyin.com/aweme/v1/web/aweme/detail/?device_platform=webapp&aid=6383&channel=channel_pc_web&pc_client_type=1&version_code=170400&version_name=17.4.0&aweme_id=7329956157827616051"

# 将URL参数转换为字典
url_params = dict([param.split("=")
                  for param in url_str.split("?")[1].split("&")])
print("URL params:", url_params)

bogus = ABogus()
a_bogus = bogus.get_value(url_params)
# URL 编码
a_bogus_encoded = quote(a_bogus, safe='')
print("\na_bogus:", a_bogus_encoded[:50], "...")
print("\nSUCCESS: a_bogus generated on VM!")
