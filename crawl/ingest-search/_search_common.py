#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/_search_common.py — 搜索型平台(boss/jd/linkedin/tieba)共用助手

提供:
  - slugify(s)              文件名安全化
  - search_opencli(cmd)     调 opencli 原生适配器(走 common.opencli_bridge.run_adapter,
                           2026-07-21: 不再注入 NO_PROXY, VPN 自动路由 + 瞬时错误重试), 返回解析后 list
  - write_md(out_dir, fname, content)  写出 md 并返回 (title, author, md_path, None) 元组
  - mmdd(date)              由 YYYYMMDD / 今天 → mmdd 文件名前缀

搜索型平台统一契约与 URL 型一致: crawl_batch(date) 返回
  [(title, author, md_path, images_dir), ...]   (images_dir 恒为 None)
"""
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

SKILL_ROOT = str(Path(__file__).resolve().parent.parent)
if SKILL_ROOT not in sys.path:
    sys.path.insert(0, SKILL_ROOT)


def slugify(s, max_len=40):
    s = (s or "").strip()
    s = re.sub(r"[^\w\u4e00-\u9fff\-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:max_len] if s else "untitled"


def mmdd(date_str=None):
    """date_str 支持 6 位 YYMMDD(260716) 或 8 位 YYYYMMDD(20260716) → mmdd(0716); 无参用今天。

    注意: pipeline 传入的是 YYMMDD(6位), 必须用 %y%m%d 解析(YYYY 会把 2607 当成 2607 年).
    """
    if date_str:
        for fmt in ("%y%m%d", "%Y%m%d"):
            try:
                return datetime.strptime(date_str, fmt).strftime("%m%d")
            except ValueError:
                continue
    return date.today().strftime("%m%d")


def today_full():
    return date.today().isoformat()


def search_opencli(cmd, retry_empty=True):
    """调 opencli 适配器, 返回解析后的 list(dict)。失败/空返回 []。"""
    from common.opencli_bridge import run_adapter
    data = run_adapter(list(cmd), retries=6, timeout=120, retry_empty=retry_empty)
    if data is None:
        return []
    return data if isinstance(data, list) else []


def write_md(out_dir, fname, content):
    """写出 md 到 out_dir/fname, 返回 (title, author, md_path, None)。"""
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    p = d / fname
    p.write_text(content, encoding="utf-8")
    return None, None, str(p), None
