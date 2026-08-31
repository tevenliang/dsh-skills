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
            date_str: 日期字符串，如 "0826" 或 "2026-08-31"。默认为今天 (MMDD 格式)。
        """
        if date_str is None:
            date_str = datetime.now().strftime("%m%d")
        
        # 同时支持 MMDD 和 YYYY-MM-DD 两种格式
        if len(date_str) == 4:  # MMDD
            mmdd = date_str
            # 用当前年份补全 (不要假设 20xx, 否则年份显示错)
            year = datetime.now().year
            ymd = f"{year}-{date_str[:2]}-{date_str[2:4]}"
        else:  # YYYY-MM-DD
            ymd = date_str
            mmdd = date_str[5:7] + date_str[8:10]
        
        date_full = ymd  # 用于显示
        index_file = self.subscription_dir / f"{mmdd}-index.md"
        
        # 收集今日所有笔记
        all_notes = []  # (platform, author, note_file, title)
        
        today_prefix = ymd  # e.g. "2026-08-31"
        
        for platform in ['douyin', 'bilibili', 'xiaohongshu']:
            platform_notes = self.subscription_dir / platform
            if not platform_notes.exists():
                continue
            
            # 递归扫描 (xiaohongshu 用 <author>/ 子目录)
            for note_file in platform_notes.rglob("*.md"):
                # 跳过备份文件
                if note_file.name.endswith('.bak') or '.bak.' in note_file.name:
                    continue
                try:
                    fname = note_file.name
                    
                    if platform == 'xiaohongshu':
                        # 小红书: 文件名用笔记发布日; 但我们关心"今天抓的"= mtime 是今天
                        # 用文件 mtime 判断
                        mtime = note_file.stat().st_mtime
                        mtime_date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
                        is_today = (mtime_date == today_prefix)
                    else:
                        # 抖音/B站: 文件名格式 <MMDD>-<title>.md, MMDD 是抓取日
                        is_today = fname.startswith(mmdd + "-")
                    
                    if not is_today:
                        continue
                    
                    content = note_file.read_text(encoding='utf-8')
                    
                    # 提取标题 (去掉日期前缀)
                    title = note_file.stem
                    if fname.startswith(mmdd + "-") and (mmdd + "-") in title:
                        title = title[len(mmdd)+1:]  # 去掉 "0826-" 前缀
                    elif fname.startswith(ymd + "_") and (ymd + "_") in title:
                        title = title[len(ymd)+1:]   # 去掉 "2026-08-26_" 前缀
                    elif fname.startswith(ymd + "-") and (ymd + "-") in title:
                        title = title[len(ymd)+1:]   # 去掉 "2026-08-26-" 前缀
                    
                    # 提取作者
                    author = ""
                    for line in content.split('\n'):
                        if line.startswith('author: ') or line.startswith('author:'):
                            author = line.split(':', 1)[1].strip().strip('"').strip("'")
                            break
                    
                    if not author:
                        # 从路径推断 (xiaohongshu/<author>/<file>.md)
                        rel_parts = note_file.relative_to(platform_notes).parts
                        if len(rel_parts) >= 2:
                            author = rel_parts[0]
                        else:
                            author = "未知作者"
                    
                    # 相对路径 (从 subscription/ 目录开始)
                    rel_path = note_file.relative_to(self.subscription_dir)
                    
                    all_notes.append((platform, author, str(rel_path), title))
                except Exception as e:
                    continue
        
        if not all_notes:
            print(f"    [index] No notes found for {mmdd} (ymd={ymd})")
            return
        
        # 按平台分组
        content_lines = []
        
        platforms_order = ['douyin', 'bilibili', 'xiaohongshu']
        platform_names = {'douyin': '抖音', 'bilibili': 'B站', 'xiaohongshu': '小红书'}
        
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
                    # note_file 已经是相对 subscription/ 的路径, 直接拼
                    content_lines.append(f"### {title}\n")
                    content_lines.append(f"![[subscription/{note_file}]]\n\n")
                content_lines.append("\n")
        
        index_content = "\n".join(content_lines)
        index_file.write_text(index_content, encoding='utf-8')
        print(f"    [index] Generated {index_file.name} with {len(all_notes)} notes")
    
    def _find_existing_by_video_id(self, platform: str, video_id: str) -> Optional[Path]:
        """扫描 vault 中是否已有该 video_id 的笔记（跨子目录跨日期）
        
        匹配策略（按优先级）:
        1. frontmatter 的 video_id: 字段（新版 crawler）
        2. frontmatter 的 uid: 字段（旧版 Mac 系统）
        3. frontmatter 的 source_url 包含该 bvid（所有版本都有）
        
        Returns: 已存在的文件路径，若不存在返回 None
        """
        platform_notes = self.subscription_dir / platform
        if not platform_notes.exists():
            return None
        bid = str(video_id)
        # 精确匹配: video_id: xxx 或 uid: xxx
        exact_re = re.compile(
            r'^video_id:\s*' + re.escape(bid) + r'\s*$',
            re.IGNORECASE | re.MULTILINE
        )
        uid_re = re.compile(
            r'^uid:\s*' + re.escape(bid) + r'\s*$',
            re.IGNORECASE | re.MULTILINE
        )
        # 宽松匹配: source_url 包含 bvid（如 https://www.bilibili.com/video/BVxxx）
        url_re = re.compile(r'https?://[^\s\'\"]]+/video/' + re.escape(bid) + r'[^\s\'\"]]*', re.IGNORECASE)
        for md_file in platform_notes.rglob('*.md'):
            try:
                text = md_file.read_text(encoding='utf-8')
                if exact_re.search(text) or uid_re.search(text) or url_re.search(text):
                    return md_file
            except Exception:
                continue
        return None

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
        image_links: list = None,
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
            发布的文件路径；若视频已存在则返回已有文件路径（不重复写入）
        """
        if tags is None:
            tags = []
        
        # 清理标题/ID 用于文件名；把视频ID也加进文件名，避免"无标题"等同名视频互相覆盖
        safe_id = sanitize_filename(str(video_id), max_bytes=30)
        safe_title = sanitize_filename(title, max_bytes=150)
        
        # 如果 title 就是视频 ID 本身（desc 为空的情况），文件名不再重复叠加视频 ID
        if safe_title == safe_id:
            safe_title = ""
        
        # 确定日期：如果传入了 publish_date（YYYY-MM-DD 格式），使用它；否则用当前时间
        if publish_date and len(publish_date) >= 10:
            # publish_date 格式: 2026-08-28，取月日部分
            date_str = publish_date[5:7] + publish_date[8:10]  # "0828"
        else:
            date_str = datetime.now().strftime("%m%d")
        
        # 平台笔记目录 (在 subscription 下)
        platform_notes = self.subscription_dir / platform
        platform_notes.mkdir(parents=True, exist_ok=True)
        
        # 命名策略：优先 {date}-{title}.md（保留旧系统清爽格式），
        # 如果同名文件已存在再加 video_id 防覆盖；空 title 直接用 video_id
        if not safe_title:
            note_file = platform_notes / f"{date_str}-{safe_id}.md"
        else:
            candidate = platform_notes / f"{date_str}-{safe_title}.md"
            if not candidate.exists():
                note_file = candidate
            else:
                # 已有同名文件，附加 video_id 短哈希避免覆盖
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
            image_links=image_links,
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
    
    def publish_xhs_note(
        self,
        note_id: str,
        title: str,
        author: str,
        source_url: str,
        desc: str = "",
        transcript: str = "",
        summary: str = "",
        likes: str = "",
        comments: str = "",
        favorites: str = "",
        tags: list = None,
        image_links: list = None,
        publish_date: str = "",
        publish_time_raw: str = "",
    ) -> Path:
        """小红书专用发布方法
        
        文件路径: subscription/xiaohongshu/<author>/<YYYY-MM-DD>_<title>.md
        对齐 Mac 老程序的文件命名和 frontmatter 格式。
        
        Args:
            note_id: 小红书 note_id (24位hex)
            title: 笔记标题
            author: 作者
            source_url: 原始链接 (含 xsec_token)
            desc: 笔记正文
            transcript: 转录文本 (视频用)
            summary: 总结
            likes/comments/favorites: 互动数据
            tags: 话题标签
            image_links: 图片 wikilink 列表
            publish_date: 笔记发布日期 YYYY-MM-DD (用于文件名)
            publish_time_raw: 笔记发布时间 YYYY-MM-DD_HH:MM:SS
        """
        if tags is None:
            tags = []
        
        # 清理标题用于文件名 (Mac 老程序允许保留特殊字符如 🔥)
        safe_title = sanitize_filename(title, max_bytes=120)
        safe_id = note_id  # 24 hex chars
        
        # 平台笔记目录 (subscription/xiaohongshu/<author>/)
        platform_notes = self.subscription_dir / "xiaohongshu" / author
        platform_notes.mkdir(parents=True, exist_ok=True)
        
        # 日期：优先用 publish_date（笔记真实发布日期），否则用今天
        if publish_date and len(publish_date) >= 10:
            date_str = publish_date  # "2026-08-31"
        else:
            date_str = datetime.now().strftime("%Y-%m-%d")
        
        # 文件名: <YYYY-MM-DD>_<title>.md (对齐 mac 格式)
        if not safe_title:
            note_file = platform_notes / f"{date_str}-{safe_id}.md"
        else:
            candidate = platform_notes / f"{date_str}_{safe_title}.md"
            if not candidate.exists():
                note_file = candidate
            else:
                # 同名已存在，加 note_id 短哈希防覆盖
                note_file = platform_notes / f"{date_str}_{safe_id}_{safe_title}.md"
        
        # 备份已存在的文件
        if note_file.exists():
            backup = note_file.with_suffix(f".md.bak.{datetime.now().strftime('%H%M%S')}")
            note_file.rename(backup)
        
        # 构建 markdown (xiaohongshu 专用 frontmatter)
        content = self._build_xhs_note(
            note_id=note_id,
            title=title,
            author=author,
            source_url=source_url,
            desc=desc,
            transcript=transcript,
            summary=summary,
            likes=likes,
            comments=comments,
            favorites=favorites,
            tags=tags,
            image_links=image_links,
            publish_date=publish_date,
            publish_time_raw=publish_time_raw,
        )
        
        note_file.write_text(content, encoding='utf-8')
        
        # 更新聚合页 (xhs-hot)
        self._update_hot(
            platform="xiaohongshu",
            title=title,
            author=author,
            source_url=source_url,
            summary=summary or desc[:200],
            video_id=note_id,
        )
        
        return note_file
    
    def _build_xhs_note(
        self,
        note_id: str,
        title: str,
        author: str,
        source_url: str,
        desc: str,
        transcript: str,
        summary: str,
        likes: str,
        comments: str,
        favorites: str,
        tags: list,
        image_links: list,
        publish_date: str,
        publish_time_raw: str,
    ) -> str:
        """小红书专用 markdown 构建 (对齐 mac 老程序格式)"""
        import json as _json
        
        # frontmatter
        tags_json = _json.dumps(tags, ensure_ascii=False) if tags else "[]"
        transcript_avail = "true" if transcript else "false"
        likes_val = likes or "0"
        comments_val = comments or "0"
        favorites_val = favorites or "0"
        publish_time = publish_time_raw or (publish_date + "_00:00:00" if publish_date else "")
        
        fm = f"""---
title: "{title}"
author: "{author}"
source_url: {source_url}
category: xiaohongshu
transcript_available: {transcript_avail}
source: xhs-downloader
publish_time_raw: {publish_time}
uid: {note_id}
note_id: {note_id}
likes: {likes_val}
comments: {comments_val}
favorites: {favorites_val}
tags: {tags_json}
---

"""
        
        # 标题
        body = f"# {title}\n\n"
        
        # 作者
        body += f"**作者**: {author}\n\n"
        
        # 描述 (desc)
        if desc:
            body += "## 描述\n\n"
            body += f"{desc}\n\n"
        
        # 摘要
        if summary:
            body += "## 摘要\n\n"
            body += f"{summary}\n\n"
        
        # 转录 (视频用)
        if transcript:
            body += "## 转录\n\n"
            body += f"{transcript}\n\n"
        
        # 图片
        if image_links:
            body += "## 图片\n\n"
            for link in image_links:
                body += f"![[{link}]]\n\n"
        
        # 原始链接
        body += "## 链接\n\n"
        body += f"- 原始链接: {source_url}\n"
        
        return fm + body
    
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
        image_links: list = None,
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
        
        # 图片（小红书图文帖）
        if image_links:
            body += "\n## 图片\n\n"
            for link in image_links:
                body += f"![[{link}]]\n"
        
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
        """检查视频是否已处理（跨子目录、跨 run 持久化）
        
        检查顺序:
        1. 旧 Mac 缓存文件 (~/.dsh/skills/crawl/ominicrawl-core/state/.subscription-crawl-cache.json)
        2. vault 已有文件内容（video_id / uid / source_url 中的 bvid）
        """
        bid = str(video_id)
        
        # ── 1. 旧 Mac 系统缓存（bvid 列表）──────────────────────────────
        import json as _json
        old_cache_path = Path.home() / ".dsh/skills/crawl/ominicrawl-core/state/.subscription-crawl-cache.json"
        if old_cache_path.exists():
            try:
                cache = _json.loads(old_cache_path.read_text(encoding="utf-8"))
                # bilibili → bvid 列表，douyin → aweme_id 列表
                if bid in cache.get(platform, []):
                    return True
            except Exception:
                pass
        
        # ── 2. vault 已有文件内容扫描（跨子目录）────────────────────────
        platform_dir = self.subscription_dir / platform
        if not platform_dir.exists():
            return False
        
        # 精确匹配 frontmatter 字段
        exact_re = re.compile(
            r'^video_id:\s*' + re.escape(bid) + r'\s*$',
            re.IGNORECASE | re.MULTILINE
        )
        uid_re = re.compile(
            r'^uid:\s*' + re.escape(bid) + r'\s*$',
            re.IGNORECASE | re.MULTILINE
        )
        # 宽松匹配: source_url / bare bvid in content
        url_or_bid_re = re.compile(
            r'https?://[^\s\'\"<>]+/video/' + re.escape(bid) + r'[^\s\'\"<>]*|[\s/](' + re.escape(bid) + r')[\s/]',
            re.IGNORECASE
        )
        for md_file in platform_dir.rglob("*.md"):   # ← 修复: 用 rglob 扫描子目录
            try:
                content = md_file.read_text(encoding='utf-8')
                if (exact_re.search(content) or uid_re.search(content) or
                        video_id in content or f"video/{video_id}" in content or
                        url_or_bid_re.search(content)):
                    return True
            except Exception:
                continue
        
        return False
