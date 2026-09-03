#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/migrate_media_to_cos.py — 历史 00_inbox 文章图片迁移到腾讯 COS

扫描 00_inbox/*.md 里所有 ![[media/<plat>/<author>/<file>]] 本地 wikilink:
  1. 定位本地文件 vault/media/<plat>/<author>/<file>
  2. picgo 批量上传 → COS URL
  3. 改写 md: wikilink → ![image](https://cos-url)
  4. 上传成功删除本地文件 (COS 成为唯一存储)

用法: python tools/migrate_media_to_cos.py [--dry-run]
"""
import argparse
import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

VAULT = Path("/home/ubuntu/webdav/steven_vault")
INBOX = VAULT / "00_inbox"
MEDIA = VAULT / "media"
TEMP_DIR = Path("/tmp/clipper-images-migrate")
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# 从 crawl-vm 借 picgo_uploader
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from picgo_uploader import upload_paths

WIKILINK_RE = re.compile(r"!\[\[(media/[^\]|]+)(?:\|[^\]]*)?\]\]")


def collect_refs():
    """扫描所有 00_inbox md, 返回 [(md_path, [(wikilink, media_rel, local_path)])]"""
    results = []
    for md_file in sorted(INBOX.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        refs = []
        for m in WIKILINK_RE.finditer(text):
            media_rel = m.group(1).strip()
            local = MEDIA / media_rel[len("media/"):]
            if local.exists():
                refs.append((m.group(0), media_rel, local))
        if refs:
            results.append((md_file, refs))
    return results


def upload_batch(files):
    """上传一批文件 (先复制到临时目录避免中文名问题), 返回 {src: url}"""
    tmp_map = {}   # str(tmp) -> src
    tmp_list = []
    for src in files:
        ext = src.suffix or ".jpg"
        tmp = TEMP_DIR / f"{uuid.uuid4().hex}{ext}"
        try:
            shutil.copy2(src, tmp)
            tmp_list.append(tmp)
            tmp_map[str(tmp)] = src
        except Exception:
            pass
    if not tmp_list:
        return {}

    urls, failed = upload_paths(tmp_list)
    result = {}
    for i, tmp in enumerate(tmp_list):
        url = urls[i] if i < len(urls) else ""
        if url:
            # key 统一用 str(src), 与主循环 str(local) 匹配
            result[str(tmp_map[str(tmp)])] = url
    # 清理临时文件
    for tmp in tmp_list:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
    return result


def main():
    parser = argparse.ArgumentParser(description="迁移 media 图片到 COS")
    parser.add_argument("--dry-run", action="store_true", help="只扫描统计, 不上传")
    parser.add_argument("--rewrite-only", action="store_true",
                        help="不做上传 (文件已在 COS), 仅改写 md + 删除本地文件")
    args = parser.parse_args()

    all_refs = collect_refs()
    total_files = sum(len(r[1]) for r in all_refs)
    print(f"发现 {len(all_refs)} 篇文章引用 {total_files} 个本地图片文件")

    if args.dry_run:
        for md_file, refs in all_refs:
            print(f"  {md_file.name}: {len(refs)} 张")
        return

    # 收集全量去重文件列表
    all_files = {}
    for md_file, refs in all_refs:
        for _wikilink, media_rel, local in refs:
            all_files[str(local)] = local

    print(f"去重后 {len(all_files)} 个唯一文件")

    url_map = {}
    if args.rewrite_only:
        print("--rewrite-only: 跳过上传, 仅改写引用 + 删除本地文件")
    else:
        # 分批上传 (每批 15 张)
        files = list(all_files.values())
        for i in range(0, len(files), 15):
            batch = files[i:i + 15]
            print(f"  上传批次 {i // 15 + 1}/{(len(files) + 14) // 15} ({len(batch)} 张)...")
            result = upload_batch(batch)
            url_map.update(result)
            print(f"    成功 {len(result)}/{len(batch)}")
        print(f"共上传成功 {len(url_map)}/{len(files)}")

    # 改写 md + 删除已上传的本地文件
    total_rewritten = 0
    for md_file, refs in all_refs:
        text = md_file.read_text(encoding="utf-8")
        changed = False
        for wikilink, media_rel, local in refs:
            url = url_map.get(str(local))
            if url:
                alt = Path(media_rel).stem
                text = text.replace(wikilink, f"![{alt}]({url})")
                changed = True
                total_rewritten += 1
        if changed:
            md_file.write_text(text, encoding="utf-8")
            print(f"  ✏️  改写: {md_file.name}")

    # 删除已上传的本地文件
    for local in all_files.values():
        if str(local) in url_map:
            try:
                local.unlink(missing_ok=True)
            except Exception:
                pass
    print(f"\n✅ 完成: 改写 {total_rewritten} 处引用, 删除 {len(url_map)} 个本地文件")


if __name__ == "__main__":
    main()