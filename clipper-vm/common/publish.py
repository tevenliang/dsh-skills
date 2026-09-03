#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
common/publish.py — clipper-vm 出口: vault/00_inbox/MMDD-<safe-title>.md

参考 Mac common-publish/publish_vault.py push():
  - 图片物化: 复制 images_dir 里的图到 vault/media/<plat>/<author>/,
    正文里 images/xxx 引用改写为 wikilink ![[media/...]]
  - 命名: MMDD-<safe-title>.md (用户要求的出口格式)
  - 总结注入: 若提供了 summary, 写入正文顶部 "## 摘要" 小节
"""
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from .util import sanitize_filename, mmdd


class VaultPublisher:
    """发布单条剪藏笔记到 00_inbox"""

    def __init__(self, vault_root):
        self.vault_root = Path(vault_root)
        self.inbox_dir = self.vault_root / "00_inbox"
        self.media_dir = self.vault_root / "media"
        # 去重缓存 (相同 platform:item_id 不重复发布)
        self.cache_path = Path.home() / ".agents/state/clipper-vm-cache.json"
        self._cache = self._load_cache()

    def _load_cache(self) -> dict:
        if self.cache_path.exists():
            try:
                return json.loads(self.cache_path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_cache(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2), encoding="utf-8")

    def is_processed(self, platform: str, item_id: str) -> bool:
        return f"{platform}:{item_id}" in self._cache

    def mark_processed(self, platform: str, item_id: str, title: str = ""):
        key = f"{platform}:{item_id}"
        self._cache[key] = {
            "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "title": title,
        }
        self._save_cache()

    # ── 图片物化 ─────────────────────────────────────────────

    def _materialize_images(self, platform: str, author: str, md_text: str,
                            images_dir) -> str:
        """把 images/xxx 引用物化到 vault/media/<plat>/<author>/, 改写为 wikilink。

        Returns: 改写后的 md 文本
        """
        if not images_dir or not Path(images_dir).exists():
            return md_text

        dest_root = self.media_dir / platform / (author or "unknown")
        dest_root.mkdir(parents=True, exist_ok=True)

        img_re = re.compile(r'!\[([^\]]*)\]\((images/[^)\s]+)\)')

        def _rewrite(m):
            alt = m.group(1)
            rel = m.group(2)
            src = Path(images_dir) / Path(rel).name
            if not src.exists():
                return m.group(0)
            dest = dest_root / src.name
            if dest.exists():
                dest = dest_root / f"{dest.stem}_{datetime.now().strftime('%H%M%S')}{dest.suffix}"
            try:
                shutil.copy2(src, dest)
                rel_path = f"media/{platform}/{dest.parent.name}/{dest.name}"
                return f"![[{rel_path}]]"
            except Exception as e:
                print(f"      ⚠️ 图片物化失败: {e}")
                return m.group(0)

        return img_re.sub(_rewrite, md_text)

    # ── 发布 ─────────────────────────────────────────────────

    def publish(self, platform: str, md_path, title: str, author: str = "",
                source_url: str = "", images_dir=None, publish_date: str = "",
                transcript: str = "", summary: str = "") -> Optional[Path]:
        """发布到 00_inbox。

        Args:
            platform: douyin/bilibili/xiaohongshu/generic/wechat
            md_path: fetcher 生成的 md
            title: 标题 (用于文件名)
            author: 作者
            source_url: 原始链接
            images_dir: 图片目录
            publish_date: 发布日期 YYYY-MM-DD (决定文件 MMDD 前缀)
            transcript: 转录文本 (视频平台)
            summary: LLM 总结 (bilibili/douyin/generic)

        Returns:
            发布文件路径, 失败返回 None
        """
        md_path = Path(md_path)
        if not md_path.exists():
            print(f"    ⚠️ md 不存在: {md_path}")
            return None

        text = md_path.read_text(encoding="utf-8")

        # 图片物化
        text = self._materialize_images(platform, author, text, images_dir)

        # 检查是否已有同源文件 (frontmatter source_url 相同 → 跳过, 防重复)
        title = title or "untitled"
        if publish_date and len(publish_date) >= 10:
            date_str = publish_date[5:7] + publish_date[8:10]
        else:
            date_str = mmdd()

        safe_title = sanitize_filename(title, max_bytes=150) or "untitled"

        inbox = self.inbox_dir
        inbox.mkdir(parents=True, exist_ok=True)
        candidate = inbox / f"{date_str}-{safe_title}.md"
        n = 2
        while candidate.exists():
            candidate = inbox / f"{date_str}-{safe_title}-{n}.md"
            n += 1

        # 剥离 fetcher 生成的前 frontmatter
        body = text
        if text.startswith("---\n"):
            idx = text.find("\n---\n", 4)
            if idx >= 0:
                body = text[idx + 6:]

        fm_lines = [
            "---",
            f"platform: {platform}",
            f'title: "{sanitize_filename(title, max_bytes=300) or ""}"',
            f'author: "{author or ""}"',
        ]
        if source_url:
            fm_lines.append(f"source_url: {source_url}")
        if publish_date:
            fm_lines.append(f"publish_date: {publish_date}")
        if transcript:
            fm_lines.append(f"transcript_chars: {len(transcript)}")
        fm_lines.append(f"created: {datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}")
        fm_lines.append("---")
        fm_lines.append("")

        # 正文组装: 标题 + 链接 + 摘要 + 转录 + 原 body
        out = "\n".join(fm_lines)
        out += f"# {safe_title}\n\n"
        if source_url:
            out += f"**原始链接**: [{source_url}]({source_url})\n\n"
        if summary:
            out += "## 摘要\n\n" + summary.strip() + "\n\n"
        if transcript:
            out += "## 转录\n\n" + transcript.strip() + "\n\n"
        out += "---\n\n"
        out += body.strip() + "\n"

        candidate.write_text(out, encoding="utf-8")
        print(f"  ✅ inbox: {candidate.name}")
        return candidate