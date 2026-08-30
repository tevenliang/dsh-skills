#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
common/util.py — 通用工具函数
"""
import re
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional


def truncate_bytes(s: str, max_bytes: int) -> str:
    """按字节截断字符串（UTF-8 边界安全），不破坏多字节字符。

    Args:
        s: 输入字符串
        max_bytes: 最大字节数

    Returns:
        截断后的字符串，确保 encoded bytes <= max_bytes
    """
    b = s.encode('utf-8')
    if len(b) <= max_bytes:
        return s
    # 回退到最后一个完整 UTF-8 字符边界
    cut = max_bytes
    while cut > 0 and (b[cut] & 0xC0) == 0x80:
        cut -= 1
    return b[:cut].decode('utf-8', errors='replace')


def sanitize_filename(name: str, max_bytes: int = 50) -> str:
    """将字符串转换为安全的文件名（字节安全截断版本）。

    剔除会破坏 Obsidian 双链解析的字符：
    # 是标题锚点、| 是别名分隔、^ 是块引用、[ ] 是链接括号。
    """
    # 先移除 #（话题标签），避免文件名里出现锚点符号
    name = name.replace('#', '')
    # 替换其它非法/特殊字符
    name = re.sub(r'[<>:"/\\|?*^\[\]]', '_', name)
    # 移除多余空格
    name = re.sub(r'\s+', '_', name.strip())
    # 按字节安全截断（max_bytes 参数语义已变更为字节数）
    if len(name.encode('utf-8')) > max_bytes:
        name = truncate_bytes(name, max_bytes)
    return name


def yymmdd(ts: Optional[int] = None) -> str:
    """时间戳转 YYMMDD 格式"""
    if ts is None:
        dt = datetime.now()
    else:
        dt = datetime.fromtimestamp(ts)
    return dt.strftime('%m%d')


def format_duration(ms: int) -> str:
    """毫秒转 MM:SS 或 HH:MM:SS"""
    s = ms // 1000
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def load_json(path: Path) -> dict:
    """安全加载 JSON 文件"""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return {}


def save_json(path: Path, data: dict):
    """安全保存 JSON 文件"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def extract_video_id_from_url(url: str) -> Optional[tuple[str, str]]:
    """从 URL 提取平台和视频 ID
    
    Returns:
        (platform, video_id) or None
    """
    # 抖音
    m = re.search(r'douyin\.com/video/(\d+)', url)
    if m:
        return ('douyin', m.group(1))
    
    # 抖音短链接
    m = re.search(r'v\.douyin\.com/([a-zA-Z0-9]+)', url)
    if m:
        return ('douyin', m.group(1))  # 需要进一步解析
    
    # B站
    m = re.search(r'bilibili\.com/video/(BV[a-zA-Z0-9]+)', url)
    if m:
        return ('bilibili', m.group(1))
    
    return None


def extract_bvid(url: str) -> Optional[str]:
    """从 URL 提取 B站 BV 号"""
    m = re.search(r'bilibili\.com/video/(BV[a-zA-Z0-9]+)', url)
    if m:
        return m.group(1)
    return None


def extract_aweme_id(url: str) -> Optional[str]:
    """从 URL 提取抖音视频 ID"""
    m = re.search(r'douyin\.com/video/(\d+)', url)
    if m:
        return m.group(1)
    m = re.search(r'v\.douyin\.com/([a-zA-Z0-9]+)', url)
    if m:
        return m.group(1)
    return None


def md5(text: str) -> str:
    """计算 MD5"""
    return hashlib.md5(text.encode()).hexdigest()


def truncate(text: str, max_len: int = 100, suffix: str = "...") -> str:
    """截断文本"""
    if len(text) <= max_len:
        return text
    return text[:max_len - len(suffix)] + suffix
