#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clip.py — clipper-vm 主流程 (链路二: 剪藏队列)

入口: vault/01_my_notes/clip.md
出口: vault/00_inbox/MMDD-<safe-title>.md

流程 (对齐 Mac cmd_clip):
  1. 读 clip.md → extract_urls → 逐个 URL
  2. canonical_key 判平台 → fetchers/<plat>.crawl(url, tmp) → (title, author, md, images)
  3. 视频平台: 下载音频 → 转 WAV → Groq 转录 (bilibili/douyin/xhs 视频)
  4. bilibili/douyin/generic: LLM 总结
  5. publish → 00_inbox
  6. 成功 → 写 cache + 从 clip.md 删行

用法:
  python -m clip [--dry-run] [--limit N]
"""
import argparse
import asyncio
import importlib
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

# 让 clipper-vm 根目录可 import (clip.py 直接位于根)
SKILL_DIR = Path(__file__).resolve().parent
for _p in (str(SKILL_DIR), str(SKILL_DIR / "common"), str(SKILL_DIR / "fetchers")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from clipboard import read_clip_text, extract_urls, canonical_key, remove_url_from_note
from common.util import load_yaml
from common.transcribe import TranscriptionService, convert_to_wav
from common.summarize import SummarizationService
from common.publish import VaultPublisher
from fetchers.base import URL_PLATFORMS, SUMMARIZE_PLATFORMS, async_download_url_to_file

# 视频平台 (需要转录)
VIDEO_TRANSCRIBE_PLATFORMS = {"douyin", "bilibili", "xiaohongshu"}


def load_config() -> dict:
    cfg = load_yaml(SKILL_DIR / "config.yaml")
    return cfg or {}


def detect_platform(url):
    return canonical_key(url)[0]


def resolve_b23(url) -> str:
    """b23.tv 短链 → 完整 B站 URL (只保留干净 video 链接, 去 query)"""
    if "b23.tv" not in url:
        return url
    try:
        import httpx
        resp = httpx.get(url, follow_redirects=True, timeout=10)
        final = str(resp.url)
        # 提取干净的 BV 链接
        import re as _re
        m = _re.search(r'(https?://www\.bilibili\.com/video/BV[0-9A-Za-z]+)', final)
        if m:
            return m.group(1)
        return final
    except Exception:
        return url


def _extract_title_from_transcript(transcript: str, author: str = "") -> str:
    """从转录文本提取标题 (首句截断)"""
    import re
    text = transcript.strip()
    if not text:
        return ""
    # 取第一句话, 截断到 40 字
    m = re.split(r"[。！？!?\n]", text, maxsplit=1)[0]
    m = m.strip().strip("，,：:")
    if len(m) > 40:
        m = m[:40]
    return m


async def process_url(url: str, publisher, transcribe, summarize, config, dry_run=False):
    """处理单个 URL (对齐 Mac process_url + cmd_clip 单条逻辑)。

    Returns: (ok, item_id) — ok 是否成功, item_id 用于 cache
    """
    url = resolve_b23(url)
    plat = detect_platform(url)
    label = {
        "bilibili": "B站", "douyin": "抖音", "xiaohongshu": "小红书",
        "generic": "通用网页", "wechat": "微信公众号",
    }.get(plat, plat)

    if plat not in URL_PLATFORMS:
        print(f"⏭️  不支持的平台: {url[:70]}")
        return False, None

    # 检查 cache
    item_id = canonical_key(url)[1]
    if publisher.is_processed(plat, item_id):
        print(f"♻️  [{label}] 已处理过, 跳过: {url[:60]}")
        return True, item_id

    print(f"\n🚀 抓取 [{label}]: {url[:80]}")

    tmp = tempfile.mkdtemp(prefix="clipper_")
    try:
        # 1. fetcher 抓取
        mod = importlib.import_module(f"fetchers.{plat}")
        if plat in ("douyin", "bilibili", "xiaohongshu"):
            ret = await mod.crawl(url, tmp, config)
        else:
            ret = await asyncio.to_thread(mod.crawl, url, tmp, config)

        if ret is None or len(ret) < 3:
            print(f"   ⏭️  fetcher 返回异常, 跳过: {url[:60]}")
            return False, item_id

        if plat in ("douyin", "bilibili", "xiaohongshu"):
            title, author, md_path, images_dir = ret
        else:
            title, author, md_path, images_dir = ret

        if not title or not md_path:
            print(f"   ⏭️  fetcher 主动跳过 (title/md 为 None)")
            return False, item_id

        print(f"   📰 {title}")

        # 2. 视频平台: 下载音频 → 转录
        transcript = ""
        if plat in VIDEO_TRANSCRIBE_PLATFORMS:
            # 从 md frontmatter 读 audio_url
            audio_url = _read_audio_url_from_md(md_path)
            if audio_url:
                print(f"    Downloading audio...")
                mp3_path = Path(tmp) / "audio.mp3"
                ua = _user_agent_for(plat)
                referer = {"douyin": "https://www.douyin.com/",
                           "bilibili": "https://www.bilibili.com/",
                           "xiaohongshu": "https://www.xiaohongshu.com/"}[plat]
                ok = await async_download_url_to_file(audio_url, mp3_path, ua, referer,
                                                      proxy=config.get("vm", {}).get("proxy", ""))
                if ok and mp3_path.exists() and mp3_path.stat().st_size > 10000:
                    wav_path = Path(tmp) / "audio.wav"
                    wav = convert_to_wav(mp3_path, wav_path)
                    if wav:
                        print(f"    Transcribing...")
                        transcript = transcribe.transcribe(wav)
                        print(f"    Transcript: {len(transcript)} chars")
                        # 标题是 ID 时从转录提取
                        if plat in ("douyin",) and (title == item_id or not title.strip()):
                            from_title = _extract_title_from_transcript(transcript, author)
                            if from_title:
                                title = from_title
                                print(f"    Title from transcript: {title[:40]}")

        # 3. 总结 (bilibili/douyin/generic)
        summary = ""
        if plat in SUMMARIZE_PLATFORMS:
            source_text = transcript or _read_md_body(md_path)
            if source_text:
                print(f"    Summarizing...")
                summary = summarize.summarize(source_text)
                if summary:
                    print(f"    Summary: {len(summary)} chars")

        # 4. 发布
        if dry_run:
            print(f"   [dry-run] 不实际发布: {title[:40]}")
            return True, item_id

        publish_date = _read_publish_date_from_md(md_path)
        result = publisher.publish(
            platform=plat,
            md_path=md_path,
            title=title,
            author=author or "",
            source_url=url,
            images_dir=images_dir or None,
            publish_date=publish_date,
            transcript=transcript,
            summary=summary,
        )
        if result:
            publisher.mark_processed(plat, item_id, title)
            return True, item_id
        return False, item_id

    except Exception as e:
        print(f"   ❌ 失败: {e}")
        import traceback
        traceback.print_exc()
        return False, item_id
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _read_audio_url_from_md(md_path) -> str:
    """从 fetcher md frontmatter 读 audio_url"""
    try:
        text = Path(md_path).read_text(encoding="utf-8")
    except Exception:
        return ""
    m = __import__("re").search(r'audio_url:\s*"?([^"\n]+?)"?\s*$', text, __import__("re").M)
    return m.group(1).strip() if m else ""


def _read_publish_date_from_md(md_path) -> str:
    try:
        text = Path(md_path).read_text(encoding="utf-8")
    except Exception:
        return ""
    import re
    m = re.search(r"publish_time:\s*(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    m = re.search(r"publish_date:\s*(\d{4}-\d{2}-\d{2})", text)
    return m.group(1) if m else ""


def _read_md_body(md_path) -> str:
    """读 md 正文 (去 frontmatter)"""
    try:
        text = Path(md_path).read_text(encoding="utf-8")
    except Exception:
        return ""
    if text.startswith("---\n"):
        idx = text.find("\n---\n", 4)
        if idx >= 0:
            text = text[idx + 6:]
    return text.strip()


def _user_agent_for(plat: str) -> str:
    if plat == "douyin":
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    if plat == "bilibili":
        return "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    return ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")


async def main():
    parser = argparse.ArgumentParser(description="clipper-vm 剪藏队列处理")
    parser.add_argument("--dry-run", action="store_true", help="只显示会处理什么, 不实际抓取发布")
    parser.add_argument("--limit", type=int, default=0, help="最多处理 N 条 (0 = 不限)")
    parser.add_argument("--url", help="直接处理指定 URL (不读 clip.md)")
    args = parser.parse_args()

    config = load_config()
    vault_root = Path(config.get("vault", "/home/ubuntu/webdav/steven_vault"))
    publisher = VaultPublisher(vault_root)
    transcribe = TranscriptionService(config.get("transcription", {}))
    summarize = SummarizationService(config.get("summarization", {}))

    # 收集 URL
    if args.url:
        urls = [args.url]
        print(f"📋 单条模式: {args.url}")
    else:
        text = read_clip_text()
        urls = extract_urls(text)
        if not urls:
            print("📋 clip.md 中暂无链接, 结束。")
            return
        print(f"📋 队列发现 {len(urls)} 个链接:")
        for u in urls:
            print(f"   - {canonical_key(u)[0]:<10} {u[:70]}")
        print()

    processed = kept = 0
    for url in urls:
        if args.limit > 0 and processed >= args.limit:
            break
        plat = detect_platform(url)
        if plat not in URL_PLATFORMS:
            print(f"⏭️  不支持的平台(保留): {url[:70]}")
            kept += 1
            continue

        ok, item_id = await process_url(
            url, publisher, transcribe, summarize, config, dry_run=args.dry_run)

        if ok and item_id:
            # 成功 (含已处理缓存命中) → 从队列删行
            if not args.dry_run:
                remove_url_from_note(url)
            processed += 1
            # 请求间隔 (防风控)
            delay = config.get("crawler", {}).get("request_delay", 3)
            if len(urls) > 1:
                await asyncio.sleep(delay)
        else:
            kept += 1

    print(f"\n{'[DRY-RUN] ' if args.dry_run else ''}完成: 处理 {processed} 条, 保留 {kept} 条")


if __name__ == "__main__":
    asyncio.run(main())