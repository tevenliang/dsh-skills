#!/usr/bin/env python3
from pathlib import Path
import sys

ABOGUS_PATH = Path.home() / ".agents/skills/crawl/ingest-douyin/douyin_api/crawlers/douyin/web/abogus.py"
print(f"ABOGUS_PATH: {ABOGUS_PATH}")
print(f"ABOGUS_PATH.parent: {ABOGUS_PATH.parent}")
print(f"Exists: {ABOGUS_PATH.exists()}")

sys.path.insert(0, str(ABOGUS_PATH.parent))
print(f"sys.path[0]: {sys.path[0]}")

import importlib
mod = importlib.import_module("abogus")
print(f"Module: {mod}")
print(f"Module file: {mod.__file__}")
