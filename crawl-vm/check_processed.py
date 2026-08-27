#!/usr/bin/env python3
"""检查已处理的视频"""
import re
from pathlib import Path
from common.publish_vault import VaultPublisher

vault = Path('/home/ubuntu/webdav/steven_vault')
publisher = VaultPublisher(vault)

processed = set()
notes_dir = vault / 'notes/douyin'
if notes_dir.exists():
    for f in notes_dir.glob('*.md'):
        content = f.read_text()
        for line in content.split('\n'):
            if 'video/' in line and 'douyin.com' in line:
                m = re.search(r'video/(\d+)', line)
                if m:
                    processed.add(m.group(1))

print(f'Processed: {len(processed)} videos')
print('Sample:', list(processed)[:5])
