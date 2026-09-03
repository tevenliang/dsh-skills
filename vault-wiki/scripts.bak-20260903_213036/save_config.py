#!/usr/bin/env python3
"""
save_config.py — 将 init 结果写入 ~/.llm_wiki.setting.json 并输出 JSON 摘要（vault 版）

所有值从环境变量读取（vault 路径，无飞书 token）：
  WIKI_NAME, PARENT_DIR, STORAGE_TYPE(vault)
  ROOT_PATH, INDEX_PATH, LOG_PATH, AGENTS_PATH
  RAW_SUBDIRS（空格分隔）
  RAW_MODE, RAW_SOURCE_PATH（raw 装配模式）
  TODAY
"""

import json
import os
import shutil
import sys

CONFIG_PATH = os.path.expanduser("~/.llm_wiki.setting.json")

entry = {
    "wiki_name":     os.environ["WIKI_NAME"],
    "storage_type":  os.environ.get("STORAGE_TYPE", "vault"),
    "parent_dir":    os.environ["PARENT_DIR"],
    "root_path":     os.environ["ROOT_PATH"],
    "index_path":    os.environ["INDEX_PATH"],
    "log_path":      os.environ["LOG_PATH"],
    "agents_path":   os.environ["AGENTS_PATH"],
    "raw_mode":      os.environ.get("RAW_MODE", "create"),
    "raw_source_path": os.environ.get("RAW_SOURCE_PATH", ""),
    "raw_subdirs":   os.environ.get("RAW_SUBDIRS", "").split(),
    "created_at":    os.environ["TODAY"],
}

cfg = {"wikis": []}

if os.path.exists(CONFIG_PATH):
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        if not isinstance(cfg.get("wikis"), list):
            cfg["wikis"] = []
    except (json.JSONDecodeError, ValueError):
        backup = CONFIG_PATH + ".bak"
        shutil.copy2(CONFIG_PATH, backup)
        print(f"WARNING: 配置文件损坏，已备份到 {backup}，重新创建", file=sys.stderr)
        cfg = {"wikis": []}

cfg["wikis"] = [w for w in cfg["wikis"] if w.get("wiki_name") != entry["wiki_name"]]
cfg["wikis"].append(entry)

with open(CONFIG_PATH, "w") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)

print(json.dumps(entry, ensure_ascii=False, indent=2))
