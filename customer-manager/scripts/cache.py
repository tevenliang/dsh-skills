from __future__ import annotations
"""
Excel 缓存管理。

设计:
- 缓存路径:~/.cache/customer-manager/excel_cache.json
- 缓存结构:{file_id: {mtime, version, fetched_at, cells: [...]}}
- 失效策略:
  1. TTL 默认 10 分钟（防止短时间重复 get-file-info）
  2. 云端 mtime 与缓存 mtime 不一致 → 重读
  3. 云端 version 与缓存 version 不一致 → 重读
- 手动刷新:search.py --refresh 强制重读

只缓存"全表"（用于 list / 统计 / 多客户查询）。
单行查询不走缓存（直接 get-row 一次开销 < 1s）。
"""

import json
import time
from pathlib import Path

CACHE_DIR = Path.home() / ".cache" / "customer-manager"
CACHE_FILE = CACHE_DIR / "excel_cache.json"
DEFAULT_TTL_SEC = 600  # 10 分钟


class CacheError(RuntimeError):
    pass


def _ensure_dir():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def load(file_id: str) -> dict | None:
    """读缓存。不存在 / JSON 损坏 → 返回 None"""
    if not CACHE_FILE.exists():
        return None
    try:
        with CACHE_FILE.open() as f:
            data = json.load(f)
        entry = data.get(file_id)
        if not entry:
            return None
        return entry
    except (json.JSONDecodeError, OSError) as e:
        # 缓存损坏不致命,返回 None 触发重读
        return None


def is_fresh(entry: dict, current_mtime: int, current_version: int,
             ttl_sec: int = DEFAULT_TTL_SEC) -> bool:
    """
    缓存是否新鲜？
    三个条件必须同时满足:
    1. 缓存时间未过期（ttl）
    2. 云端 mtime 与缓存一致
    3. 云端 version 与缓存一致
    """
    if not entry:
        return False

    # TTL 检查
    age = time.time() - entry.get("fetched_at", 0)
    if age > ttl_sec:
        return False

    # mtime 检查
    if entry.get("mtime") != current_mtime:
        return False

    # version 检查（防御性,部分场景 mtime 不变但内容变了）
    if entry.get("version") != current_version:
        return False

    return True


def save(file_id: str, mtime: int, version: int, cells: list[dict]):
    """写缓存（覆盖旧 entry）"""
    _ensure_dir()

    # 读现有缓存（如果存在）
    if CACHE_FILE.exists():
        try:
            with CACHE_FILE.open() as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}

    data[file_id] = {
        "mtime": mtime,
        "version": version,
        "fetched_at": time.time(),
        "cells": cells,
    }

    # 原子写：先写临时文件，再 rename（防中途崩溃损坏）
    tmp = CACHE_FILE.with_suffix(".json.tmp")
    with tmp.open("w") as f:
        json.dump(data, f, ensure_ascii=False)
    tmp.replace(CACHE_FILE)


def get_cells(file_id: str, current_mtime: int, current_version: int,
              ttl_sec: int = DEFAULT_TTL_SEC) -> list[dict] | None:
    """
    取缓存的 cells（自动判断新鲜度）。
    返回 None 表示缓存不可用,需要重读。
    """
    entry = load(file_id)
    if not entry:
        return None
    if not is_fresh(entry, current_mtime, current_version, ttl_sec):
        return None
    return entry.get("cells", [])
