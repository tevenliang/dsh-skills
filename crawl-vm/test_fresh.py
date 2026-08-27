#!/usr/bin/env python3
"""测试新鲜转录 - 检查标点"""
import asyncio
import sys
sys.path.insert(0, '/home/ubuntu/.dsh/skills/crawl-vm')
from pathlib import Path
from platforms.douyin.crawler import DouyinCrawler

async def test():
    crawler = DouyinCrawler()
    # 黄士铨看世界
    sec_uid = 'MS4wLjABAAAARGJtMMMujtgxbnl18CQHeUiTdopr5C--P4I3t80KvumwcZw2di4vfeteEnBhYI-x'
    videos = await crawler.fetch_user_post_videos(sec_uid, 0, 5)
    print(f'Found {len(videos)} videos')
    for v in videos[:3]:
        vid = v.get('aweme_id', 'N/A')
        title = v.get('desc', '无标题')[:50]
        print(f'  - {vid}: {title}')

asyncio.run(test())
