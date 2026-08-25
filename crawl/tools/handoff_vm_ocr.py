#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handoff_vm_ocr.py — 小红书 OCR 交接模块 (crawl 3.1.x)

职责:
  把 Mac 本地已下载的小红书笔记（含 images_dir）rsync 到 VM 的 ocr_inbox/，
  由 VM 侧 ocr_daemon.py 异步完成 OCR → 覆盖写回 vault。

handoff 结构（对齐 VM ocr_daemon 契约）:
  ocr_inbox/{note_id}/
  ├── {note_id}.meta.json   ← 元数据
  ├── {note_id}.md           ← 原始 md（wikilinks 引用 media/）
  └── {note_id}_images/     ← 图片目录（rsync）
      ├── 0.jpg
      └── 1.png

OCR=Y 的博主笔记由 ingest-xhs/xiaohongshu.py 在 publish 后调用。

依赖: rsync（Mac 自带）+ Mac→VM SSH 免密。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

VM_HOST = "175.178.210.156"
VM_USER = "ubuntu"
VM_OCR_INBOX = "/home/ubuntu/crawl-transcribe/ocr_inbox"


def _load_vm_cfg():
    try:
        import yaml
        cfg_path = Path(__file__).resolve().parent.parent / "config.yaml"
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        vm = cfg.get("vm", {}) or {}
        return (
            vm.get("host", VM_HOST),
            vm.get("user", VM_USER),
            vm.get("crawl_transcribe_ocr_inbox", VM_OCR_INBOX),
        )
    except Exception:
        return VM_HOST, VM_USER, VM_OCR_INBOX


def handoff_xhs_ocr_to_vm(md_path: str, images_dir: str,
                           note_id: str, author: str, title: str,
                           source_url: str, publish_date: str = "",
                           timeout: int = 300):
    """把小红书笔记图片目录 + md + meta 打包上传 VM OCR inbox。

    Args:
        md_path:      Mac 本地 md 文件绝对路径（已写 vault，包含 ![[media/xhs/...]] 引用）
        images_dir:   Mac 本地图片目录（如 /Users/.../images/<note>/, 可能已被 rmtree）
        note_id:     小红书笔记 ID（文件名基础名）
        author:      博主名
        title:       笔记标题
        source_url:  原始链接
        publish_date: 发布日期 YYYY-MM-DD
        timeout:     rsync 超时秒数（图片多时需要较长）
    Returns:
        bool: 上传成功 True / 失败 False
    """
    md_path = Path(md_path)
    if not md_path.exists():
        print(f"  ⚠️ [ocr-handoff] md 不存在: {md_path}")
        return False

    host, user, inbox = _load_vm_cfg()

    # 2026-08-15 fix: vault_root/media_xhs_dir 用于 images_dir 不存在时
    # 兜底从 media/xhs/ 里 fuzzy 找同 author+title 的图.
    # 用 Path.home() 直达, 不依赖 __file__ 相对深度.
    vault_root = Path.home() / "Documents" / "steven_vault"
    media_xhs_dir = vault_root / "media" / "xhs"

    # 建立 VM 目录
    remote_base = f"{user}@{host}:{inbox}/{note_id}"
    remote_note_dir = f"{user}@{host}:{inbox}/{note_id}"

    # 1. 构造 meta.json
    meta = {
        "platform": "xiaohongshu",
        "author": author or "未知作者",
        "title": title or note_id,
        "source_url": source_url or "",
        "publish_date": publish_date or "",
        "note_id": note_id,
    }

    import tempfile, os
    tmpdir = Path(tempfile.mkdtemp(prefix="ocr_handoff_"))
    try:
        meta_file = tmpdir / f"{note_id}.meta.json"
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        # 2. 复制 md 到临时目录
        md_copy = tmpdir / f"{note_id}.md"
        shutil.copy2(md_path, md_copy)

        # 3. 建立 images 子目录并复制图片
        img_dir = tmpdir / f"{note_id}_images"
        img_dir.mkdir(parents=True, exist_ok=True)
        src_images = Path(images_dir) if images_dir else None
        copied = 0
        if src_images and src_images.exists() and src_images.is_dir():
            for img in sorted(src_images.iterdir()):
                if img.is_file() and img.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
                    shutil.copy2(img, img_dir / img.name)
                    copied += 1
        # 2026-08-18 fix: images_dir 可能已被 publish_vault._materialize_images()
        # 删掉 (rmtree). 改用精确方案: 从 md 原文解析 wikilink ![[media/xhs/...]]
        # → 在 media/xhs/ 精确找同名文件.
        if copied == 0 and media_xhs_dir.exists():
            # 1. 解析 md 里的 wikilink -> 相对路径
            wikilink_paths = re.findall(r'!\[\[(media/xhs/[^\]]+)\]\]', md_path.read_text(encoding="utf-8"))
            for rel_path in wikilink_paths:
                vault_file = media_xhs_dir.parent / rel_path
                if vault_file.exists() and vault_file.is_file():
                    shutil.copy2(vault_file, img_dir / vault_file.name)
                    copied += 1
            # 2. 兜底 fuzzy (当 md 没有 wikilink 时)
            if copied == 0 and author and title:
                def _xhs_normalize(s):
                    if not s:
                        return ""
                    out = []
                    for ch in s:
                        if ch.isalnum() or ch == "_" or "\u4e00" <= ch <= "\u9fff":
                            out.append(ch)
                        else:
                            out.append("_")
                    return re.sub(r"_+", "_", "".join(out)).strip("_")
                author_norm = _xhs_normalize(author)
                title_norm = _xhs_normalize(title)[:12]
                if author_norm and title_norm:
                    author_pat = re.compile("[ _]*".join(re.escape(c) for c in author_norm))
                    title_pat = re.compile("[ _]*".join(re.escape(c) for c in title_norm))
                    for f in sorted(media_xhs_dir.iterdir()):
                        if not f.is_file() or f.suffix.lower() not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
                            continue
                        if author_pat.search(f.name) and title_pat.search(f.name):
                            shutil.copy2(f, img_dir / f.name)
                            copied += 1

        # 4. rsync 整个 note_id 目录到 VM
        cmd = [
            "rsync", "-a", "--timeout", str(timeout),
            str(tmpdir) + "/",
            f"{user}@{host}:{inbox}/{note_id}/",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 60)
        if r.returncode != 0:
            print(f"  ⚠️ [ocr-handoff] rsync 失败 rc={r.returncode}: {r.stderr.strip()[:200]}")
            return False

        img_count = len([p for p in img_dir.iterdir() if p.is_file()])
        if img_count == 0:
            print(f"  ⚠️ [ocr-handoff] 已上传 VM 但无图片可传: {note_id}/  (images_dir={images_dir}, title={title[:30]!r})")
        else:
            print(f"  ✅ [ocr-handoff] 已上传 VM OCR inbox → {note_id}/ (+ {img_count} 张图)")

        return True

    except subprocess.TimeoutExpired:
        print(f"  ⚠️ [ocr-handoff] rsync 超时 ({timeout}s)")
        return False
    except Exception as e:
        print(f"  ⚠️ [ocr-handoff] 异常: {e}")
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 5:
        print("用法: python handoff_vm_ocr.py <md_path> <images_dir> <note_id> <author> [title] [source_url] [publish_date]")
        sys.exit(1)
    ok = handoff_xhs_ocr_to_vm(
        sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4],
        title=sys.argv[5] if len(sys.argv) > 5 else "",
        source_url=sys.argv[6] if len(sys.argv) > 6 else "",
        publish_date=sys.argv[7] if len(sys.argv) > 7 else "",
    )
    sys.exit(0 if ok else 1)
