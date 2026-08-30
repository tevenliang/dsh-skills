#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
common/publish_vault.py — 发布到 vault 模块

输出格式:
- vault/subscription/<platform>-hot.md  (聚合页)
- vault/notes/<platform>/<date>-<title>.md (单条笔记)
"""
import re
from pathlib import Path
from datetime import datetime
from typing import Optional

from .util import sanitize_filename


class VaultPublisher:
    def __init__(self, vault_root: Path):
        self.vault_root = Path(vault_root)
        self.subscription_dir = self.vault_root / "subscription"
        
        # 确保目录存在
        self.subscription_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_daily_index(self, date_str: str = None):
        """生成每日 index.md，按作者聚合所有平台的笔记
        
        Args:
            date_str: 日期字符串，如 "0826"。默认为今天。
        """
        if date_str is None:
            date_str = datetime.now().strftime("%m%d")
        
        date_full = f"20{date_str[:2]}-{date_str[2:4]}-{date_str[4:6]}"  # YYYY-MM-DD
        
        index_file = self.subscription_dir / f"{date_str}-index.md"
        
        # 收集今日所有笔记
        all_notes = []  # (platform, author, note_file, title)
        
        for platform in ['douyin', 'bilibili']:
            platform_notes = self.subscription_dir / platform
            if not platform_notes.exists():
                continue
            
            for note_file in platform_notes.glob("*.md"):
                try:
                    # 检查是否是今天的笔记 (文件名格式: 0826-标题.md)
                    if not note_file.name.startswith(date_str):
                        continue
                    
                    content = note_file.read_text(encoding='utf-8')
                    
                    # 提取标题 (去掉日期前缀)
                    title = note_file.stem[len(date_str)+1:]  # 去掉 "0826-" 前缀
                    
                    # 提取作者
                    author = ""
                    for line in content.split('\n'):
                        if line.startswith('author: '):
                            author = line.replace('author: ', '').strip()
                            break
                    
                    if not author:
                        author = "未知作者"
                    
                    all_notes.append((platform, author, note_file.name, title))
                except Exception as e:
                    continue
        
        if not all_notes:
            print(f"    [index] No notes found for {date_str}")
            return
        
        # 按平台分组
        content_lines = []
        
        platforms_order = ['douyin', 'bilibili']
        platform_names = {'douyin': '抖音', 'bilibili': 'B站'}
        
        for platform in platforms_order:
            platform_notes = [n for n in all_notes if n[0] == platform]
            if not platform_notes:
                continue
            
            content_lines.append(f"# {platform_names[platform]}\n")
            
            # 按作者分组
            by_author = {}
            for p, author, note_file, title in platform_notes:
                if author not in by_author:
                    by_author[author] = []
                by_author[author].append((note_file, title))
            
            for author, notes in sorted(by_author.items()):
                content_lines.append(f"## {author}\n")
                for note_file, title in notes:
                    # 使用 subscription/ 目录的路径
                    content_lines.append(f"### {title}\n")
                    content_lines.append(f"![[subscription/{platform}/{note_file}]]\n\n")
                content_lines.append("\n")
        
        index_content = "\n".join(content_lines)
        index_file.write_text(index_content, encoding='utf-8')
        print(f"    [index] Generated {index_file.name} with {len(all_notes)} notes")
    
    def publish(
        self,
        platform: str,
        video_id: str,
        title: str,
        author: str,
        source_url: str,
        transcript: str,
        summary: str = "",
        publish_date: str = "",
        tags: list = None,
    ) -> Path:
        """发布视频笔记到 vault
        
        Args:
            platform: 平台 (douyin/bilibili)
            video_id: 视频 ID
            title: 视频标题
            author: 作者
            source_url: 原始链接
            transcript: 转录文本
            summary: 总结文本
            publish_date: 发布日期 (YYYY-MM-DD)
            tags: 标签
            
        Returns:
            发布的文件路径
        """
        if tags is None:
            tags = []
        
        # 清理标题/ID 用于文件名；把视频ID也加进文件名，避免"无标题"等同名视频互相覆盖
        safe_id = sanitize_filename(str(video_id), max_bytes=30)
        safe_title = sanitize_filename(title, max_bytes=150)
        
        # 确定日期：如果传入了 publish_date（YYYY-MM-DD 格式），使用它；否则用当前时间
        if publish_date and len(publish_date) >= 10:
            # publish_date 格式: 2026-08-28，取月日部分
            date_str = publish_date[5:7] + publish_date[8:10]  # "0828"
        else:
            date_str = datetime.now().strftime("%m%d")
        
        # 平台笔记目录 (在 subscription 下)
        platform_notes = self.subscription_dir / platform
        platform_notes.mkdir(parents=True, exist_ok=True)
        
        # 单条笔记文件（含 video_id 防重名）
        note_file = platform_notes / f"{date_str}-{safe_id}-{safe_title}.md"
        
        # 如果文件已存在，先备份（避免重复写入）
        if note_file.exists():
            backup = note_file.with_suffix(f".md.bak.{datetime.now().strftime('%H%M%S')}")
            note_file.rename(backup)
        
        # 构建 markdown
        content = self._build_note(
            platform=platform,
            video_id=video_id,
            title=title,
            author=author,
            source_url=source_url,
            transcript=transcript,
            summary=summary,
            publish_date=publish_date,
            tags=tags,
        )
        
        note_file.write_text(content, encoding='utf-8')
        
        # 更新聚合页
        self._update_hot(
            platform=platform,
            title=title,
            author=author,
            source_url=source_url,
            summary=summary or transcript[:200],
            video_id=video_id,
        )
        
        return note_file
    
    def _build_note(
        self,
        platform: str,
        video_id: str,
        title: str,
        author: str,
        source_url: str,
        transcript: str,
        summary: str,
        publish_date: str,
        tags: list,
    ) -> str:
        """构建单条笔记 markdown"""
        tags_str = ", ".join(f'"{t}"' for t in tags) if tags else "[]"
        
        # frontmatter
        fm = f"""---
platform: {platform}
author: {author}
source_url: {source_url}
publish_date: {publish_date}
tags: [{tags_str}]
---

"""
        
        # 标题
        body = f"# {title}\n\n"
        
        # 链接
        body += "## 链接\n\n"
        body += f"- 原始链接: {source_url}\n\n"
        
        # 总结
        if summary:
            body += "## 摘要\n\n"
            body += f"{summary}\n\n"
        
        # 转录
        body += "## 正文\n\n"
        body += f"{transcript}\n"
        
        return fm + body
    
    def _update_hot(
        self,
        platform: str,
        title: str,
        author: str,
        source_url: str,
        summary: str,
        video_id: str,
    ):
        """更新聚合页"""
        hot_file = self.subscription_dir / f"{platform}-hot.md"
        
        # 读取现有内容
        existing = ""
        if hot_file.exists():
            existing = hot_file.read_text(encoding='utf-8')
        
        # 解析现有的 ## YYYY-MM-DD 小节
        date_str = datetime.now().strftime('%Y-%m-%d')
        
        # 构建新条目
        new_entry = f"""### [{title}]({source_url})
- 作者: {author}
- 摘要: {summary[:200]}...
- 时间: {date_str}

"""
        
        # 检查当天是否已有小节
        date_pattern = f"## {date_str}"
        if date_pattern in existing:
            # 追加到当天小节
            parts = existing.split(date_pattern)
            if len(parts) == 2:
                header, rest = parts
                # 找到下一个 ## 或文件末尾
                next_section = rest.find("\n## ")
                if next_section == -1:
                    content = rest
                else:
                    content = rest[:next_section]
                
                existing = header + date_pattern + content + "\n" + new_entry + rest[len(content):]
        else:
            # 添加新的日期小节
            if existing.strip():
                existing += "\n"
            existing += f"## {date_str}\n\n{new_entry}"
        
        hot_file.write_text(existing, encoding='utf-8')
    
    def is_processed(self, platform: str, video_id: str) -> bool:
        """检查视频是否已处理"""
        # 检查 subscription 目录
        platform_dir = self.subscription_dir / platform
        if not platform_dir.exists():
            return False
        
        # 简单检查：搜索文件中是否包含该 video_id
        for md_file in platform_dir.glob("*.md"):
            try:
                content = md_file.read_text(encoding='utf-8')
                if video_id in content or f"video/{video_id}" in content:
                    return True
            except:
                continue
        
        return False
