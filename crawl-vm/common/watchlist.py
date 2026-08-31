#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
common/watchlist.py — 监控列表读取模块

支持两种格式:
1. 简格式: | 平台 | 博主 | ID | 备注 |
2. 旧格式(Douyin): | 博主 | 分类 | URL |
   URL 格式: https://www.douyin.com/user/MS4wLjABAAAA...
"""
import re
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Author:
    platform: str
    name: str
    author_id: str  # mid (B站) / sec_user_id (抖音) / user_id (小红书)
    remark: str = ""


def extract_douyin_sec_uid(url: str) -> Optional[str]:
    """从 Douyin 用户主页 URL 提取 sec_user_id
    
    URL 格式: https://www.douyin.com/user/MS4wLjABAAAA...
    """
    # 匹配 /user/MS4wLjABAAAA... 模式
    m = re.search(r'/user/(MS4wLjABAAAA[a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    
    # 直接是 sec_uid 的情况
    if url.startswith('MS4wLjABAAAA'):
        return url.split('?')[0].split()[0]
    
    return None


def extract_bilibili_mid(url: str) -> Optional[str]:
    """从 Bilibili space URL 提取 mid
    
    URL 格式: https://space.bilibili.com/{mid}
    """
    m = re.search(r'space\.bilibili\.com/(\d+)', url)
    if m:
        return m.group(1)
    return None


def extract_xiaohongshu_user_id(url: str) -> Optional[str]:
    """从小红书用户主页 URL 提取 user_id
    
    URL 格式: https://www.xiaohongshu.com/user/profile/{user_id}
    user_id 是 24 位十六进制字符串, 如 5f92b728000000000101d9f7
    """
    m = re.search(r'xiaohongshu\.com/user/profile/([a-f0-9]{24})', url)
    if m:
        return m.group(1)
    # 直接是 user_id 的情况
    if len(url) == 24 and re.match(r'^[a-f0-9]{24}$', url):
        return url
    return None


def parse_watchlist(vault_root: Path) -> List[Author]:
    """解析 watchlist.md
    
    Returns:
        Author 列表
    """
    # 正确路径: vault/subscription/watchlist.md
    watchlist_file = vault_root / "subscription" / "watchlist.md"
    
    if not watchlist_file.exists():
        print(f"    [watchlist] watchlist.md not found: {watchlist_file}")
        return []
    
    content = watchlist_file.read_text(encoding='utf-8')
    
    authors = []
    lines = content.split('\n')
    
    current_platform = None
    in_table = False
    
    for line in lines:
        line_stripped = line.strip()
        
        # 检测平台标题
        if line_stripped.startswith('## '):
            if '抖音' in line_stripped or 'douyin' in line_stripped.lower():
                current_platform = 'douyin'
                in_table = False
            elif 'bili' in line_stripped.lower():
                current_platform = 'bilibili'
                in_table = False
            elif '小红书' in line_stripped or 'xhs' in line_stripped.lower() or 'xiaohongshu' in line_stripped.lower():
                current_platform = 'xiaohongshu'
                in_table = False
            else:
                current_platform = None
                in_table = False
            continue
        
        if not current_platform:
            continue
        
        # 检测表格分隔符
        if re.match(r'\|[\s\-:]+\|[\s\-:]+\|', line_stripped):
            in_table = True
            continue
        
        if not in_table:
            continue
        
        if not line_stripped.startswith('|'):
            continue
        
        parts = [p.strip() for p in line_stripped.split('|')]
        
        # 根据平台判断格式
        if current_platform == 'douyin':
            # 旧格式: | 博主 | 分类 | URL |
            if len(parts) < 4:
                continue
            
            name = parts[1]
            category = parts[2]
            url_or_id = parts[3]
            
            if not name or name in ('博主', '---'):
                continue
            
            author_id = extract_douyin_sec_uid(url_or_id) or ""
            
            authors.append(Author(
                platform=current_platform,
                name=name,
                author_id=author_id,
                remark=category,
            ))
        
        elif current_platform == 'bilibili':
            # 格式: | 博主 | 分类 | URL |
            # URL 格式: https://space.bilibili.com/{mid}
            if len(parts) < 4:
                continue
            
            name = parts[1]
            category = parts[2]
            url = parts[3]
            
            # 跳过表头
            if name in ('博主', '---') or not name:
                continue
            
            # 从 URL 提取 mid
            author_id = extract_bilibili_mid(url) or ""
            
            authors.append(Author(
                platform='bilibili',
                name=name,
                author_id=author_id,
                remark=category,
            ))

        elif current_platform == 'xiaohongshu':
            # 格式: | 博主 | 分类 | URL |
            # URL 格式: https://www.xiaohongshu.com/user/profile/{user_id}
            if len(parts) < 4:
                continue
            
            name = parts[1]
            category = parts[2]
            url = parts[3]
            
            if name in ('博主', '---') or not name:
                continue
            
            author_id = extract_xiaohongshu_user_id(url) or ""
            
            authors.append(Author(
                platform='xiaohongshu',
                name=name,
                author_id=author_id,
                remark=category,
            ))
    
    print(f"    [watchlist] Loaded {len(authors)} authors")
    for a in authors:
        id_display = a.author_id[:30] + "..." if len(a.author_id) > 30 else a.author_id if a.author_id else "(NO ID)"
        print(f"      - {a.platform}: {a.name} ({id_display})")
    
    return authors


def get_author_id_by_name(authors: List[Author], platform: str, name: str) -> Optional[str]:
    """根据平台和名称查找 author_id"""
    for a in authors:
        if a.platform == platform and a.name == name:
            return a.author_id
    return None
