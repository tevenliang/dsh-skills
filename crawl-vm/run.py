#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline/run.py — crawl-vm 主流程

职责:
1. 读取 watchlist 获取博主列表
2. 遍历平台爬虫获取视频
3. 逐条处理：下载 → 转录 → 总结 → 发布
4. 输出事件流到 state/run_*.events.jsonl
"""
import argparse
import asyncio
import json
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

# 添加模块路径
SKILL_DIR = Path(__file__).resolve().parent  # /home/ubuntu/.dsh/skills/crawl-vm
sys.path.insert(0, str(SKILL_DIR))
sys.path.insert(0, str(SKILL_DIR / "common"))

from common.util import yymmdd
from common.watchlist import parse_watchlist
from common.transcribe import TranscriptionService, convert_to_wav
from common.summarize import SummarizationService
from common.publish_vault import VaultPublisher

from platforms.douyin.crawler import DouyinCrawler
from platforms.bilibili.crawler import BilibiliCrawler
from platforms.xiaohongshu.crawler import XiaohongshuCrawler, DEFAULT_UA


def load_config() -> dict:
    """加载配置"""
    config_file = SKILL_DIR / "config.yaml"
    import yaml
    return yaml.safe_load(config_file.read_text(encoding='utf-8'))


def load_cookie(platform: str, config: dict) -> str:
    """加载 Cookie"""
    if platform == "douyin":
        # 从 douyin config.yaml 读取
        cookie_config_path = Path(config["platforms"]["douyin"]["cookie_config"])
        import yaml
        cookie_config = yaml.safe_load(cookie_config_path.read_text(encoding='utf-8'))
        return cookie_config["TokenManager"]["douyin"]["headers"]["Cookie"]
    elif platform == "bilibili":
        cookie_file = Path.home() / ".agents" / "credentials" / "ominicrawl" / "bilibili.txt"
        return cookie_file.read_text().strip()
    elif platform == "xiaohongshu":
        cookie_file = Path.home() / ".agents" / "credentials" / "ominicrawl" / "xiaohongshu.txt"
        return cookie_file.read_text().strip()
    else:
        raise ValueError(f"Unknown platform: {platform}")


class EventLogger:
    """事件日志记录器"""
    
    def __init__(self, tag: str):
        self.tag = tag
        self.state_dir = SKILL_DIR / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建新的事件文件
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.event_file = self.state_dir / f"run_{ts}.events.jsonl"
        # 创建空文件
        self.event_file.write_text("", encoding='utf-8')
        
    def log(self, event: str, **kwargs):
        """记录事件"""
        entry = {
            "ts": datetime.now().isoformat(),
            "event": event,
            "tag": self.tag,
            **kwargs
        }
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        self.event_file.write_text(
            self.event_file.read_text(encoding='utf-8') + line,
            encoding='utf-8'
        )
        # 同时打印
        print(f"  [{event}] {kwargs}")


async def process_douyin_video(crawler: DouyinCrawler, aweme_id: str, publisher: VaultPublisher, 
                               transcribe: TranscriptionService, summarize: SummarizationService,
                               logger: EventLogger, config: dict):
    """处理单个抖音视频"""
    delay = config.get("crawler", {}).get("request_delay", 2)
    
    logger.log("start", platform="douyin", video_id=aweme_id)
    
    try:
        # 1. 获取视频详情
        print(f"\n  Processing douyin video: {aweme_id}")
        detail = await crawler.fetch_video_detail(aweme_id)
        if not detail:
            logger.log("failed", platform="douyin", video_id=aweme_id, reason="fetch_detail_failed")
            return False
        
        info = crawler.parse_video_info(detail)
        print(f"    title: {info['title'][:40]}")
        print(f"    author: {info['author']}")
        
        # 2. 检查是否已处理
        if publisher.is_processed("douyin", aweme_id):
            print(f"    Already processed, skipping")
            logger.log("skipped", platform="douyin", video_id=aweme_id, reason="already_processed")
            return True
        
        # 3. 获取音频 URL
        audio_url = crawler.get_audio_url(detail)
        if not audio_url:
            print(f"    No audio URL found")
            logger.log("failed", platform="douyin", video_id=aweme_id, reason="no_audio_url")
            return False
        
        # 4. 下载音频 (带重试)
        with tempfile.TemporaryDirectory() as tmpdir:
            mp3_path = Path(tmpdir) / f"{aweme_id}.mp3"
            wav_path = Path(tmpdir) / f"{aweme_id}.wav"
            
            # 重试下载
            max_retries = 2
            download_ok = False
            
            for retry in range(max_retries + 1):
                print(f"    Downloading audio (attempt {retry + 1}/{max_retries + 1})...")
                cmd = [
                    "curl", "-s", "-L", "-o", str(mp3_path),
                    "--connect-timeout", "30",
                    "--max-time", "180",
                    "-A", crawler.headers["User-Agent"],
                    "-H", f"Referer: https://www.douyin.com/",
                    audio_url
                ]
                try:
                    r = subprocess.run(cmd, timeout=200)
                except subprocess.TimeoutExpired:
                    print(f"    Download timeout")
                    if retry < max_retries:
                        await asyncio.sleep(5)
                        continue
                    else:
                        logger.log("failed", platform="douyin", video_id=aweme_id, reason="download_timeout")
                        return False
                
                if mp3_path.exists() and mp3_path.stat().st_size > 10000:
                    download_ok = True
                    break
                elif retry < max_retries:
                    print(f"    Download failed, retrying...")
                    await asyncio.sleep(3)
                    continue
            
            if not download_ok:
                print(f"    Download failed after {max_retries + 1} attempts")
                logger.log("failed", platform="douyin", video_id=aweme_id, reason="download_failed")
                return False
            
            print(f"    Downloaded: {mp3_path.stat().st_size} bytes")
            
            # 5. 转换为 WAV
            print(f"    Converting to WAV...")
            wav_path = convert_to_wav(mp3_path, wav_path)
            if not wav_path:
                print(f"    Conversion failed")
                logger.log("failed", platform="douyin", video_id=aweme_id, reason="conversion_failed")
                return False
            
            print(f"    Converted: {wav_path.stat().st_size} bytes")
            
            # 6. 转录
            print(f"    Transcribing...")
            await asyncio.sleep(0.5)  # 稍微延迟
            transcript = transcribe.transcribe(wav_path)
            if not transcript:
                print(f"    Transcription failed")
                logger.log("failed", platform="douyin", video_id=aweme_id, reason="transcribe_failed")
                return False
            
            print(f"    Transcript: {len(transcript)} chars")
            
            # 7. 总结
            print(f"    Summarizing...")
            summary = summarize.summarize(transcript)
            if summary:
                print(f"    Summary: {len(summary)} chars")
            
            # 8. 发布
            print(f"    Publishing...")
            note_file = publisher.publish(
                platform="douyin",
                video_id=aweme_id,
                title=info["title"],
                author=info["author"],
                source_url=f"https://www.douyin.com/video/{aweme_id}",
                transcript=transcript,
                summary=summary,
            )
            print(f"    Published: {note_file.name}")
            
            await asyncio.sleep(delay)
        
        logger.log("success", platform="douyin", video_id=aweme_id, title=info["title"])
        return True
        
    except Exception as e:
        print(f"    Error: {e}")
        logger.log("failed", platform="douyin", video_id=aweme_id, reason=str(e))
        return False


async def process_bilibili_video(crawler: BilibiliCrawler, bvid: str, publisher: VaultPublisher,
                                 transcribe: TranscriptionService, summarize: SummarizationService,
                                 logger: EventLogger, config: dict):
    """处理单个B站视频
    
    Returns:
        (ok, was_skipped): ok=True if successful, was_skipped=True if already processed
    """
    delay = config.get("crawler", {}).get("request_delay", 2)
    
    logger.log("start", platform="bilibili", video_id=bvid)
    
    try:
        # 1. 获取视频详情
        print(f"\n  Processing bilibili video: {bvid}")
        detail = await crawler.fetch_video_detail(bvid)
        if not detail:
            logger.log("failed", platform="bilibili", video_id=bvid, reason="fetch_detail_failed")
            return False, False
        
        title = detail.get("title", "")
        author = detail.get("owner", {}).get("name", "")
        cid = detail.get("cid", 0)
        print(f"    title: {title[:40]}")
        print(f"    author: {author}")
        print(f"    cid: {cid}")
        
        # 2. 检查是否已处理
        if publisher.is_processed("bilibili", bvid):
            print(f"    Already processed, skipping")
            logger.log("skipped", platform="bilibili", video_id=bvid, reason="already_processed")
            return True, True  # ok=True, was_skipped=True
        
        # 3. 获取播放地址
        print(f"    Getting playurl...")
        audio_url = await crawler.get_playurl(bvid, cid)
        if not audio_url:
            print(f"    No audio URL found")
            logger.log("failed", platform="bilibili", video_id=bvid, reason="no_audio_url")
            return False
        
        # 4. 下载音频 (带重试)
        with tempfile.TemporaryDirectory() as tmpdir:
            m4a_path = Path(tmpdir) / f"{bvid}.m4a"
            wav_path = Path(tmpdir) / f"{bvid}.wav"
            
            max_retries = 2
            download_ok = False
            
            for retry in range(max_retries + 1):
                print(f"    Downloading audio (attempt {retry + 1}/{max_retries + 1})...")
                cmd = [
                    "curl", "-s", "-L", "-o", str(m4a_path),
                    "--connect-timeout", "30",
                    "--max-time", "180",
                    "-A", crawler.headers["User-Agent"],
                    "-H", f"Referer: https://www.bilibili.com/",
                    audio_url
                ]
                try:
                    r = subprocess.run(cmd, timeout=200)
                except subprocess.TimeoutExpired:
                    print(f"    Download timeout")
                    if retry < max_retries:
                        await asyncio.sleep(5)
                        continue
                    else:
                        logger.log("failed", platform="bilibili", video_id=bvid, reason="download_timeout")
                        return False, False
                
                if m4a_path.exists() and m4a_path.stat().st_size > 10000:
                    download_ok = True
                    break
                elif retry < max_retries:
                    print(f"    Download failed, retrying...")
                    await asyncio.sleep(3)
                    continue
            
            if not download_ok:
                print(f"    Download failed after {max_retries + 1} attempts")
                logger.log("failed", platform="bilibili", video_id=bvid, reason="download_failed")
                return False, False
            
            print(f"    Downloaded: {m4a_path.stat().st_size} bytes")
            
            # 5. 转换为 WAV
            print(f"    Converting to WAV...")
            wav_path = convert_to_wav(m4a_path, wav_path)
            if not wav_path:
                print(f"    Conversion failed")
                logger.log("failed", platform="bilibili", video_id=bvid, reason="conversion_failed")
                return False, False
            
            print(f"    Converted: {wav_path.stat().st_size} bytes")
            
            # 6. 转录
            print(f"    Transcribing...")
            await asyncio.sleep(0.5)
            transcript = transcribe.transcribe(wav_path)
            if not transcript:
                print(f"    Transcription failed")
                logger.log("failed", platform="bilibili", video_id=bvid, reason="transcribe_failed")
                return False, False
            
            print(f"    Transcript: {len(transcript)} chars")
            
            # 7. 总结
            print(f"    Summarizing...")
            summary = summarize.summarize(transcript)
            if summary:
                print(f"    Summary: {len(summary)} chars")
            
            # 8. 发布
            print(f"    Publishing...")
            note_file = publisher.publish(
                platform="bilibili",
                video_id=bvid,
                title=title,
                author=author,
                source_url=f"https://www.bilibili.com/video/{bvid}",
                transcript=transcript,
                summary=summary,
            )
            print(f"    Published: {note_file.name}")
            
            await asyncio.sleep(delay)
        
        logger.log("success", platform="bilibili", video_id=bvid, title=title)
        return True, False  # ok=True, was_skipped=False
        
    except Exception as e:
        print(f"    Error: {e}")
        logger.log("failed", platform="bilibili", video_id=bvid, reason=str(e))
        return False, False


async def process_xiaohongshu_note(crawler: XiaohongshuCrawler, note_card: Dict,
                                     publisher: VaultPublisher,
                                     transcribe: TranscriptionService,
                                     summarize: SummarizationService,
                                     logger: EventLogger, config: dict):
    """处理单条小红书笔记

    note_card: 直接传入 note_card dict (来自 get_user_notes 或 get_homefeed 的摘要)
                不需要再调 get_note_detail (除非要正文/视频 URL)

    Returns:
        (ok, was_skipped)
    """
    delay = config.get("crawler", {}).get("request_delay", 2)

    note_id = note_card.get("note_id", "")
    xsec_token = note_card.get("xsec_token", "")
    title = note_card.get("display_title", "")
    author = (note_card.get("user", {}) or {}).get("nickname", "") or (note_card.get("user", {}) or {}).get("nick_name", "")
    note_type = note_card.get("type", "normal")

    logger.log("start", platform="xiaohongshu", note_id=note_id, title=title[:30])

    # 1. 检查是否已处理
    if publisher.is_processed("xiaohongshu", note_id):
        print(f"    Already processed, skipping")
        logger.log("skipped", platform="xiaohongshu", note_id=note_id, reason="already_processed")
        return True, True

    # 2. 获取完整详情 (含正文 desc / 视频 URL)
    try:
        detail = await crawler.get_note_detail(note_id, xsec_token)
    except Exception as e:
        print(f"    Failed to get note detail: {e}")
        logger.log("failed", platform="xiaohongshu", note_id=note_id, reason=str(e))
        return False, False

    info = crawler.parse_note_info(detail)
    title = info.get("title", title)
    desc = info.get("desc", "")
    liked = info.get("liked_count", "")
    collected = info.get("collected_count", "")
    tag_list = info.get("tag_list", []) or []
    # 提取 tag 名字列表
    tags = [t.get("name", "") for t in tag_list if isinstance(t, dict) and t.get("name")]
    # 互动数据
    interact_info = detail.get("interact_info", {}) or {}
    comments = interact_info.get("comment_count", "0")
    # 发布时间 (Unix ms → YYYY-MM-DD_HH.MM.SS)
    time_ms = info.get("time") or 0
    if time_ms:
        publish_dt = datetime.fromtimestamp(time_ms / 1000)
        publish_date = publish_dt.strftime("%Y-%m-%d")
        publish_time_raw = publish_dt.strftime("%Y-%m-%d_%H:%M:%S")
        image_date = publish_dt.strftime("%Y-%m-%d")
        image_time = publish_dt.strftime("%H.%M.%S")
    else:
        publish_date = datetime.now().strftime("%Y-%m-%d")
        publish_time_raw = ""
        image_date = publish_date
        image_time = datetime.now().strftime("%H.%M.%S")

    source_url = (f"https://www.xiaohongshu.com/discovery/item/{note_id}"
                  f"?xsec_token={xsec_token}&xsec_source=pc_web")

    # 3. 获取媒体 URL
    audio_url = crawler.get_audio_url(detail)
    image_urls = crawler.get_image_urls(detail) if not audio_url else []

    # 3b. 下载图片到 vault media 目录 (用于图文笔记)
    image_links = []
    if image_urls:
        # 文件名格式: <date>_<time>_<author>_<title>_<n>.<ext>
        safe_author = re.sub(r'[^\w\u4e00-\u9fff]', '', author) or "未知作者"
        safe_title_short = re.sub(r'[^\w\u4e00-\u9fff]', '', title)[:40]
        media_dir = publisher.subscription_dir.parent / "media" / "xhs"
        media_dir.mkdir(parents=True, exist_ok=True)

        print(f"    Downloading {len(image_urls)} images...")
        for idx, img_url in enumerate(image_urls, 1):
            # 判断扩展名 (XHS URL 通常带 !nc_n_webp_mw_1 等, 但 content-type 是 webp)
            ext = "png"  # mac 老程序都用 .png 后缀
            if ".jpg" in img_url.lower() or "image/jpeg" in img_url.lower():
                ext = "jpg"
            elif ".webp" in img_url.lower() or "_webp" in img_url.lower():
                ext = "webp"

            # 文件名: <date>_<time>_<author>_<title>_<n>.<ext> (对齐 mac 格式)
            img_file = media_dir / f"{image_date}_{image_time}_{safe_author}_{safe_title_short}_{idx}.{ext}"
            ok = await _download_url_to_file(
                img_url, img_file,
                crawler.headers_base.get("User-Agent", DEFAULT_UA),
                "https://www.xiaohongshu.com/",
            )
            if ok and img_file.exists() and img_file.stat().st_size > 0:
                # wikilink 格式: media/xhs/<file>
                rel_path = f"media/xhs/{img_file.name}"
                image_links.append(rel_path)
                print(f"      [{idx}/{len(image_urls)}] ✅ {img_file.stat().st_size} bytes")
            else:
                print(f"      [{idx}/{len(image_urls)}] ❌ download failed")

    # 3c. 处理笔记类型
    wav_path = None
    if audio_url:
        # 视频笔记: 下载 mp4 → 转 wav → 转录
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            mp4_path = tmp_path / f"{note_id}.mp4"
            wav_path = tmp_path / f"{note_id}.wav"

            print(f"    Downloading video...")
            ok = await _download_url_to_file(audio_url, mp4_path, crawler.headers_base.get("User-Agent", DEFAULT_UA),
                                               "https://www.xiaohongshu.com/")
            if not ok or not mp4_path.exists() or mp4_path.stat().st_size < 10000:
                print(f"    Video download failed")
                logger.log("failed", platform="xiaohongshu", note_id=note_id, reason="download_failed")
                return False, False

            print(f"    Downloaded: {mp4_path.stat().st_size} bytes")

            print(f"    Converting to WAV...")
            wav_path = convert_to_wav(mp4_path, wav_path)
            if not wav_path:
                logger.log("failed", platform="xiaohongshu", note_id=note_id, reason="conversion_failed")
                return False, False

            # 4. 转录
            print(f"    Transcribing...")
            await asyncio.sleep(0.5)
            transcript = transcribe.transcribe(wav_path)
            if not transcript:
                print(f"    Transcription failed")
                logger.log("failed", platform="xiaohongshu", note_id=note_id, reason="transcribe_failed")
                return False, False
            print(f"    Transcript: {len(transcript)} chars")

    elif image_urls:
        # 图文笔记: 图片已下载完成，无音频不转录
        wav_path = None
        print(f"    Image note ({len(image_urls)} images), skipping transcription")
        transcript = ""

    else:
        # 纯文字帖：无音频无图片，只有 desc 正文
        wav_path = None
        print(f"    Text-only note, publishing with desc content")
        transcript = ""

    # 5. 总结
    summary = ""
    if transcript:
        print(f"    Summarizing...")
        summary = summarize.summarize(transcript)
        if summary:
            print(f"    Summary: {len(summary)} chars")
    elif desc:
        # 纯文字帖: desc 即正文内容，作为 transcript 发布，同时做总结
        print(f"    Using desc as transcript ({len(desc)} chars)")
        transcript = desc
        print(f"    Summarizing from desc...")
        summary = summarize.summarize(desc)
        if summary:
            print(f"    Summary: {len(summary)} chars")

    # 6. 发布（小红书专用格式，对齐 mac 老程序）
    print(f"    Publishing...")
    note_file = publisher.publish_xhs_note(
        note_id=note_id,
        title=title,
        author=author,
        source_url=source_url,
        desc=desc,
        transcript=transcript,
        summary=summary,
        likes=liked,
        comments=comments,
        favorites=collected,
        tags=tags,
        image_links=image_links if image_links else None,
        publish_date=publish_date,
        publish_time_raw=publish_time_raw,
    )
    print(f"    Published: {note_file.name}")

    await asyncio.sleep(delay)

    logger.log("success", platform="xiaohongshu", note_id=note_id, title=title)
    return True, False


async def _download_url_to_file(url: str, dest: Path, user_agent: str, referer: str) -> bool:
    """下载 URL 到文件 (curl subprocess)"""
    import subprocess
    cmd = [
        "curl", "-s", "-L", "-o", str(dest),
        "--connect-timeout", "30",
        "--max-time", "180",
        "-A", user_agent,
        "-H", f"Referer: {referer}",
        url
    ]
    try:
        r = subprocess.run(cmd, timeout=200)
        return r.returncode == 0 and dest.exists() and dest.stat().st_size > 0
    except subprocess.TimeoutExpired:
        return False


async def run_platform(platform: str, config: dict, publisher: VaultPublisher,
                       transcribe: TranscriptionService, summarize: SummarizationService,
                       logger: EventLogger, video_ids: list = None, author_ids: list = None,
                       note_cards: list = None):
    """运行单个平台"""
    
    print(f"\n{'='*50}")
    print(f"Running platform: {platform}")
    print(f"{'='*50}")
    
    # 加载 Cookie
    try:
        cookie = load_cookie(platform, config)
    except Exception as e:
        print(f"Failed to load cookie for {platform}: {e}")
        return
    
    proxy = config.get("vm", {}).get("proxy", "http://127.0.0.1:7890")
    
    delay = config.get("crawler", {}).get("request_delay", 2)
    max_videos = config.get("crawler", {}).get("max_videos_per_author", 0)
    
    if platform == "douyin":
        crawler = DouyinCrawler(cookie, proxy)
        
        if video_ids:
            # 处理指定的视频
            for aweme_id in video_ids:
                await process_douyin_video(crawler, aweme_id, publisher, transcribe, summarize, logger, config)
        
        elif author_ids:
            # 从博主获取视频列表
            for author_id in author_ids:
                print(f"\nFetching videos for author: {author_id}")
                videos = await crawler.get_user_videos(sec_user_id=author_id)
                if videos is None:
                    print(f"  Failed to fetch videos, skipping")
                    continue
                print(f"  Found {len(videos)} videos")
                
                processed = 0
                for video in videos:
                    if max_videos > 0 and processed >= max_videos:
                        break
                    
                    aweme_id = video.get("aweme_id", "")
                    if aweme_id:
                        ok = await process_douyin_video(crawler, aweme_id, publisher, transcribe, summarize, logger, config)
                        if ok:
                            processed += 1
                            await asyncio.sleep(delay)
    
    elif platform == "bilibili":
        crawler = BilibiliCrawler(cookie, proxy)
        
        if video_ids:
            # 处理指定的视频
            for bvid in video_ids:
                await process_bilibili_video(crawler, bvid, publisher, transcribe, summarize, logger, config)
        
        elif author_ids:
            # 从博主获取视频列表
            for mid in author_ids:
                print(f"\nFetching videos for author mid: {mid}")
                videos = await crawler.get_user_videos(int(mid))
                if videos is None:
                    print(f"  Failed to fetch videos, skipping")
                    continue
                print(f"  Found {len(videos)} videos")
                
                processed = 0
                consecutive_skipped = 0
                for video in videos:
                    if max_videos > 0 and processed >= max_videos:
                        break
                    
                    bvid = video.get("bvid", "")
                    if bvid:
                        ok, was_skipped = await process_bilibili_video(crawler, bvid, publisher, transcribe, summarize, logger, config)
                        if ok:
                            processed += 1
                            if was_skipped:
                                consecutive_skipped += 1
                                # 如果连续跳过10个视频，认为该博主没有新内容了
                                if consecutive_skipped >= 10:
                                    print(f"  No more new videos after {consecutive_skipped} skips, moving to next author")
                                    break
                            else:
                                consecutive_skipped = 0
                            await asyncio.sleep(delay)

    elif platform == "xiaohongshu":
        crawler = XiaohongshuCrawler(cookie, proxy)
        
        if note_cards:
            # 处理指定的笔记列表 (来自 run.py 外部直接传入 note_card list)
            for card in note_cards:
                note_id = card.get("note_id", "")
                if not note_id:
                    continue
                await process_xiaohongshu_note(crawler, card, publisher, transcribe, summarize, logger, config)
        
        elif author_ids:
            # 从博主获取笔记列表
            for user_id in author_ids:
                print(f"\nFetching notes for xiaohongshu user: {user_id}")
                try:
                    notes = await crawler.get_user_notes(user_id, num=20)
                except Exception as e:
                    print(f"  Failed to fetch notes: {e}")
                    continue
                print(f"  Found {len(notes)} notes")
                
                processed = 0
                consecutive_skipped = 0
                for note_card in notes:
                    if max_videos > 0 and processed >= max_videos:
                        break
                    
                    note_id = note_card.get("note_id", "")
                    if note_id:
                        ok, was_skipped = await process_xiaohongshu_note(
                            crawler, note_card, publisher, transcribe, summarize, logger, config)
                        if ok:
                            processed += 1
                            if was_skipped:
                                consecutive_skipped += 1
                                if consecutive_skipped >= 10:
                                    print(f"  No more new notes after {consecutive_skipped} skips")
                                    break
                            else:
                                consecutive_skipped = 0
                            await asyncio.sleep(delay)


async def main():
    parser = argparse.ArgumentParser(description='crawl-vm 主流程')
    parser.add_argument('--platforms', default='all', help='平台列表 (douyin,bilibili,xiaohongshu 或 all)')
    parser.add_argument('--date', default=None, help='日期 YYYYMMDD')
    parser.add_argument('--douyin-ids', nargs='*', help='指定抖音视频 ID')
    parser.add_argument('--bilibili-ids', nargs='*', help='指定 B站视频 BV 号')
    parser.add_argument('--douyin-authors', nargs='*', help='指定抖音博主 sec_uid')
    parser.add_argument('--bilibili-authors', nargs='*', help='指定 B站博主 mid')
    parser.add_argument('--xiaohongshu-authors', nargs='*', help='指定小红书博主 user_id')
    parser.add_argument('--xiaohongshu-ids', nargs='*', help='指定小红书 note_id (手动喂详情)')
    
    args = parser.parse_args()
    
    # 加载配置
    config = load_config()
    
    # 初始化组件
    vault_root = Path(config.get("vault", "/home/ubuntu/webdav/steven_vault"))
    publisher = VaultPublisher(vault_root)
    transcribe = TranscriptionService(config.get("transcription", {}))
    summarize = SummarizationService(config.get("summarization", {}))
    
    tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger = EventLogger(tag)
    
    logger.log("start", platforms=args.platforms)
    
    print(f"crawl-vm starting...")
    print(f"  vault: {vault_root}")
    print(f"  transcription provider: {config.get('transcription', {}).get('provider')}")
    print(f"  summarization provider: {config.get('summarization', {}).get('provider')}")
    
    # 确定要运行的平台
    platforms = []
    if args.platforms == 'all':
        platforms = ['douyin', 'bilibili', 'xiaohongshu']
    else:
        platforms = args.platforms.split(',')
    
    # 遍历平台
    for platform in platforms:
        if platform not in ('douyin', 'bilibili', 'xiaohongshu'):
            continue
        
        if not config.get("platforms", {}).get(platform, {}).get("enabled", False):
            print(f"Platform {platform} is disabled, skipping")
            continue
        
        # 确定视频 ID 或博主 ID
        video_ids = None
        author_ids = None
        
        if platform == 'douyin':
            if args.douyin_ids:
                video_ids = args.douyin_ids
            elif args.douyin_authors:
                author_ids = args.douyin_authors
            # 如果都没有，从 watchlist 读取
            if not video_ids and not author_ids:
                from common.watchlist import parse_watchlist
                authors = parse_watchlist(vault_root)
                douyin_authors = [a for a in authors if a.platform == 'douyin' and a.author_id]
                author_ids = [a.author_id for a in douyin_authors]
                print(f"  [watchlist] Found {len(author_ids)} Douyin authors")
        elif platform == 'bilibili':
            if args.bilibili_ids:
                video_ids = args.bilibili_ids
            elif args.bilibili_authors:
                author_ids = args.bilibili_authors
            # 如果都没有，从 watchlist 读取
            if not video_ids and not author_ids:
                from common.watchlist import parse_watchlist
                authors = parse_watchlist(vault_root)
                bili_authors = [a for a in authors if a.platform == 'bilibili' and a.author_id]
                author_ids = [a.author_id for a in bili_authors]
                print(f"  [watchlist] Found {len(author_ids)} Bilibili authors")
        elif platform == 'xiaohongshu':
            if args.xiaohongshu_authors:
                author_ids = args.xiaohongshu_authors
            else:
                # 从 watchlist 读取
                from common.watchlist import parse_watchlist
                authors = parse_watchlist(vault_root)
                xhs_authors = [a for a in authors if a.platform == 'xiaohongshu' and a.author_id]
                author_ids = [a.author_id for a in xhs_authors]
                print(f"  [watchlist] Found {len(author_ids)} Xiaohongshu authors")
        
        await run_platform(
            platform, config, publisher, transcribe, summarize, logger,
            video_ids=video_ids, author_ids=author_ids
        )
    
    # 生成每日 index
    date_str = datetime.now().strftime("%m%d")
    publisher.generate_daily_index(date_str)
    
    logger.log("complete")
    print(f"\n{'='*50}")
    print(f"crawl-vm completed!")
    print(f"Events logged to: {logger.event_file}")
    print(f"{'='*50}")


if __name__ == "__main__":
    asyncio.run(main())
