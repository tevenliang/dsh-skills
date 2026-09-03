#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
common/publish.py — clipper-vm 出口: vault/00_inbox/MMDD-<safe-title>.md

参考 Mac common-publish/publish_vault.py push():
  - 图片存储: 默认 PicGo 上传腾讯 COS 拿 URL, md 写 ![image](https://...)
    上传失败 → fall_back_local: 复制到 vault/media/<plat>/<author>/, 改写 wikilink
  - 命名: MMDD-<safe-title>.md (用户要求的出口格式)
  - 总结注入: 若提供了 summary, 写入正文顶部 "## 摘要" 小节
"""
import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from .util import sanitize_filename, mmdd


class VaultPublisher:
    """发布单条剪藏笔记到 00_inbox"""

    def __init__(self, vault_root, image_storage: dict | None = None):
        self.vault_root = Path(vault_root)
        self.inbox_dir = self.vault_root / "00_inbox"
        self.media_dir = self.vault_root / "media"
        self.image_storage = image_storage or {}
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

    # ── 图片存储 (COS 优先, 本地兜底) ──────────────────────

    def _handle_images(self, platform: str, author: str, md_text: str,
                       images_dir) -> str:
        """处理 md 里的图片引用。

        默认: PicGo 上传腾讯 COS → ![image](https://...) URL
        upload 失败或 image_storage.enabled=false:
            fall_back_local → 复制到 vault/media/<plat>/<author>/, 改写 wikilink

        Returns: 改写后的 md 文本
        """
        if not images_dir or not Path(images_dir).exists():
            return md_text

        img_re = re.compile(r'!\[([^\]]*)\]\((images/[^)\s]+)\)')
        matches = list(img_re.finditer(md_text))
        if not matches:
            return md_text

        use_cos = (self.image_storage.get("enabled", True)
                   and self.image_storage.get("provider") == "picgo")
        on_failure = self.image_storage.get("on_failure", "fall_back_local")

        # 收集需要上传的文件列表 (去重)
        src_files = []
        for m in matches:
            src = Path(images_dir) / Path(m.group(2)).name
            if src.exists() and src not in src_files:
                src_files.append(src)

        url_map = {}  # src.name -> url
        if use_cos and src_files:
            # 先复制到临时目录 (统一扩展名风格, 避免 picgo 对中文名/特殊字符问题)
            temp_dir = Path(self.image_storage.get("temp_dir", "/tmp/clipper-images"))
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_files = []       # 上传对象列表
            temp_to_src = {}      # str(tmp) -> src.name
            for src in src_files:
                ext = src.suffix or ".jpg"
                tmp = temp_dir / f"{uuid.uuid4().hex}{ext}"
                try:
                    shutil.copy2(src, tmp)
                    temp_files.append(tmp)
                    temp_to_src[str(tmp)] = src.name
                except Exception as e:
                    print(f"      ⚠️ 复制到临时目录失败: {src.name}: {e}")

            if temp_files:
                from .picgo_uploader import upload_paths
                success_urls, failed_paths = upload_paths(temp_files)
                # success_urls[i] 严格对应 temp_files[i] (picgo_uploader 顺序保证)
                uploaded_tmp = set()
                for i, tmp in enumerate(temp_files):
                    url = success_urls[i] if i < len(success_urls) else ""
                    if url:
                        orig_name = temp_to_src.get(str(tmp), tmp.name)
                        url_map[orig_name] = url
                        uploaded_tmp.add(str(tmp))
                # 删除已上传的临时文件
                for tmp in temp_files:
                    if str(tmp) in uploaded_tmp:
                        try:
                            tmp.unlink(missing_ok=True)
                        except Exception:
                            pass
                print(f"      📤 COS 上传: {len(url_map)}/{len(src_files)} 张成功")

        # 本地兜底目录
        dest_root = self.media_dir / platform / (author or "unknown")
        dest_root.mkdir(parents=True, exist_ok=True)

        def _rewrite(m):
            alt = m.group(1)
            rel = m.group(2)
            src = Path(images_dir) / Path(rel).name
            if not src.exists():
                return m.group(0)

            # COS URL 优先
            url = url_map.get(src.name)
            if url:
                return f"![{alt}]({url})"

            # 本地兜底
            if on_failure == "fail":
                print(f"      ❌ 图片上传失败 (fail 模式): {src.name}")
                return m.group(0)

            dest = dest_root / src.name
            if dest.exists():
                dest = dest_root / f"{dest.stem}_{datetime.now().strftime('%H%M%S')}{dest.suffix}"
            try:
                if src.resolve() != dest.resolve():
                    shutil.copy2(src, dest)
                rel_path = f"media/{platform}/{dest.parent.name}/{dest.name}"
                return f"![[{rel_path}]]"
            except Exception as e:
                print(f"      ⚠️ 图片本地兜底失败: {e}")
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
        text = self._handle_images(platform, author, text, images_dir)

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