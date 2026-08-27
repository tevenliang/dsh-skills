#!/usr/bin/env python3
"""Find fresh video to test"""
import asyncio
import re
import sys
sys.path.insert(0, '/home/ubuntu/.dsh/skills/crawl-vm')

from platforms.douyin.crawler import DouyinCrawler
from pathlib import Path

async def get_fresh_video():
    cookie_path = Path.home() / ".agents/credentials/ominicrawl/douyin.txt"
    cookie = cookie_path.read_text().strip()
    
    crawler = DouyinCrawler(cookie)
    
    sec_uid = "MS4wLjABAAAARGJtMMMujtgxbnl18CQHeUiTdopr5C--P4I3t80KvumwcZw2di4vfeteEnBhYI-x"
    videos = await crawler.fetch_user_post_videos(sec_uid, 0, 10)
    
    notes_dir = Path("/home/ubuntu/webdav/steven_vault/notes/douyin")
    processed = set()
    if notes_dir.exists():
        for f in notes_dir.glob("*.md"):
            content = f.read_text()
            for m in re.findall(r'video/(\d+)', content):
                processed.add(m)
    
    for v in videos:
        vid = v.get("aweme_id", "")
        if vid and vid not in processed:
            print(f"Fresh video: {vid}")
            print(f"Title: {v.get('desc', 'N/A')[:80]}")
            return vid, v.get("desc", "N/A")
    
    print("No fresh videos found")
    return None, None

vid, title = asyncio.run(get_fresh_video())
