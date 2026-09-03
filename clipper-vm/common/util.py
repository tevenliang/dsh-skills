#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
common/util.py — clipper-vm 共用工具

注意 VM vault 文件名铁律: ext4 单文件名上限 255 字节 (UTF-8 汉字 3B)。
sanitize_filename 必须按字节截断, 避免 wsgidav [Errno 36] File name too long。
"""
import re
from pathlib import Path
from datetime import datetime


def sanitize_filename(name: str, max_bytes: int = 150) -> str:
    """文件名安全化 + 字节截断 (UTF-8 边界安全)。

    - 去掉路径分隔符/控制字符/Windows 非法字符
    - 按 max_bytes 字节截断，保证不跨 UTF-8 字符边界
    """
    s = str(name or "").strip()
    # 去非法字符: \ / : * ? " < > | 控制字符
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", s)
    s = re.sub(r'\s+', " ", s).strip()
    if not s:
        return "untitled"
    # 字节截断
    encoded = s.encode("utf-8")
    if len(encoded) <= max_bytes:
        return s
    # 从最大字节往回找安全边界
    truncated = encoded[:max_bytes]
    while truncated:
        try:
            return truncated.decode("utf-8")
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return "untitled"


def yymmdd(ts=None):
    """yyMMdd 格式日期字符串"""
    dt = datetime.fromtimestamp(ts) if ts else datetime.now()
    return dt.strftime("%y%m%d")


def mmdd(ts=None):
    """MMdd 格式日期字符串 (00_inbox 出口命名用)"""
    dt = datetime.fromtimestamp(ts) if ts else datetime.now()
    return dt.strftime("%m%d")


def load_yaml(path):
    import yaml
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))