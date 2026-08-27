#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, '/home/ubuntu/skills/crawl-vm')
from common.watchlist import parse_watchlist

authors = parse_watchlist(Path('/home/ubuntu/webdav/steven_vault'))
print("\nParsed authors:")
for a in authors:
    print(f'  {a.platform}: {a.name} -> {a.author_id[:40]}...' if a.author_id else f'  {a.platform}: {a.name} -> NO ID')
