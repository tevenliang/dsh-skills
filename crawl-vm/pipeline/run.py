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
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

# 添加模块路径
SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))
sys.path.insert(0, str(SKILL_DIR / "common"))

from common.util import yymmdd
from common.watchlist import parse_watchlist
from common.transcribe import TranscriptionService, convert_to_wav
from common.summarize import SummarizationService
from common.publish_vault import VaultPublisher

from platforms.douyin.crawler import DouyinCrawler
from platforms.bilibili.crawler import BilibiliCrawler


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
    """处理单个B站视频"""
    delay = config.get("crawler", {}).get("request_delay", 2)
    
    logger.log("start", platform="bilibili", video_id=bvid)
    
    try:
        # 1. 获取视频详情
        print(f"\n  Processing bilibili video: {bvid}")
        detail = await crawler.fetch_video_detail(bvid)
        if not detail:
            logger.log("failed", platform="bilibili", video_id=bvid, reason="fetch_detail_failed")
            return False
        
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
            return True
        
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
                        return False
                
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
                return False
            
            print(f"    Downloaded: {m4a_path.stat().st_size} bytes")
            
            # 5. 转换为 WAV
            print(f"    Converting to WAV...")
            wav_path = convert_to_wav(m4a_path, wav_path)
            if not wav_path:
                print(f"    Conversion failed")
                logger.log("failed", platform="bilibili", video_id=bvid, reason="conversion_failed")
                return False
            
            print(f"    Converted: {wav_path.stat().st_size} bytes")
            
            # 6. 转录
            print(f"    Transcribing...")
            await asyncio.sleep(0.5)
            transcript = transcribe.transcribe(wav_path)
            if not transcript:
                print(f"    Transcription failed")
                logger.log("failed", platform="bilibili", video_id=bvid, reason="transcribe_failed")
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
        return True
        
    except Exception as e:
        print(f"    Error: {e}")
        logger.log("failed", platform="bilibili", video_id=bvid, reason=str(e))
        return False


async def run_platform(platform: str, config: dict, publisher: VaultPublisher,
                       transcribe: TranscriptionService, summarize: SummarizationService,
                       logger: EventLogger, video_ids: list = None, author_ids: list = None):
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
                print(f"  Found {len(videos)} videos")
                
                processed = 0
                for video in videos:
                    if max_videos > 0 and processed >= max_videos:
                        break
                    
                    bvid = video.get("bvid", "")
                    if bvid:
                        ok = await process_bilibili_video(crawler, bvid, publisher, transcribe, summarize, logger, config)
                        if ok:
                            processed += 1
                            await asyncio.sleep(delay)


async def main():
    parser = argparse.ArgumentParser(description='crawl-vm 主流程')
    parser.add_argument('--platforms', default='all', help='平台列表 (douyin,bilibili 或 all)')
    parser.add_argument('--date', default=None, help='日期 YYYYMMDD')
    parser.add_argument('--douyin-ids', nargs='*', help='指定抖音视频 ID')
    parser.add_argument('--bilibili-ids', nargs='*', help='指定 B站视频 BV 号')
    parser.add_argument('--douyin-authors', nargs='*', help='指定抖音博主 sec_uid')
    parser.add_argument('--bilibili-authors', nargs='*', help='指定 B站博主 mid')
    
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
        platforms = ['douyin', 'bilibili']
    else:
        platforms = args.platforms.split(',')
    
    # 遍历平台
    for platform in platforms:
        if platform not in ('douyin', 'bilibili'):
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
