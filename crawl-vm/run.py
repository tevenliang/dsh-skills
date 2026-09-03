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
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
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
from common.picgo_uploader import upload_paths as picgo_upload_paths

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
        # 从 douyin config.yaml 读取 (新仓库位置)
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


def _extract_title_from_transcript(transcript: str, author: str = "") -> str:
    """从转录文本提取一句话作为标题 (抖音无 desc 视频)

    策略:
    1. 去掉开头无意义的语气词/停顿词
    2. 取第一句 (按 。！？!?<br>换行截断)
    3. 过长则用逗号断 (转录常无句号)
    4. 截取最多 40 字符
    """
    import re
    text = transcript.strip()
    if not text:
        return ""
    
    LEADING_NOISE = [
        "诶呀", "哎呀", "呃", "嗯", "啊", "这个", "那个", "就是说",
        "其实", "然后", "好了", "接下来", "今天吧", "我们先", "大家知道",
        "朋友们", "大家好", "哈喽", "hello", "hi", "em", "eh",
    ]
    
    cleaned = text
    # 最多去 3 轮语气词
    for _ in range(3):
        changed = False
        for noise in sorted(LEADING_NOISE, key=len, reverse=True):
            if cleaned.startswith(noise):
                cleaned = cleaned[len(noise):]
                changed = True
                break
        if not changed:
            break
    # 去掉此后开头的标点/空格
    cleaned = re.sub(r'^[,，.。!！?？;；:\s]+', '', cleaned)
    
    # 取第一句
    first_sentence = re.split(r'[。！？!?;；\n]', cleaned)[0].strip()
    
    # 过长 (转录常无句号): 用逗号/顿号切, 目标 8-30 字符
    if len(first_sentence) > 30:
        parts = re.split(r'[,，]', first_sentence)
        acc = ""
        for p in parts:
            if len(acc) + len(p) + 1 <= 30:
                acc += p + ","
            else:
                break
        first_sentence = acc.rstrip(",") if len(acc) >= 8 else first_sentence[:30]
    
    # 去掉尾部悬空标点 + #话题 + emoji
    first_sentence = re.sub(r'[,，.。:：\s]+$', '', first_sentence)
    first_sentence = re.sub(r'#\S+$', '', first_sentence).strip()
    first_sentence = re.sub(r'[\U0001F300-\U0001FAFF\U000026A0-\U000027BF]', '', first_sentence)
    
    # 截断 40 字符
    if len(first_sentence) > 40:
        first_sentence = first_sentence[:40].rstrip()
    if len(first_sentence.strip()) < 3:
        # fallback: 前 30 字符
        first_sentence = transcript.strip()[:30]
    
    return first_sentence.strip()


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
            
            # 7. 如果 desc 为空 (标题是 video_id), 从转录文本提取标题
            if info["title"] == str(aweme_id) or not info["title"].strip():
                from_title = _extract_title_from_transcript(transcript, info["author"])
                if from_title:
                    print(f"    Title from transcript: {from_title[:40]}")
                    info["title"] = from_title
            
            # 8. 总结
            print(f"    Summarizing...")
            summary = summarize.summarize(transcript)
            if summary:
                print(f"    Summary: {len(summary)} chars")
            
            # 9. 发布
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
            return False, False

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
    delay = config.get("crawler", {}).get("xhs_request_delay",
                     config.get("crawler", {}).get("request_delay", 5))

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

    # 3b. 处理图片: 默认走 PicGo→COS (拿 URL), 失败兜底保留本地
    image_links = []
    if image_urls:
        # 文件名格式: <date>_<time>_<author>_<title>_<n>.<ext> (对齐 mac 格式)
        safe_author = re.sub(r'[^\w\u4e00-\u9fff]', '', author) or "未知作者"
        safe_title_short = re.sub(r'[^\w\u4e00-\u9fff]', '', title)[:40]

        image_storage_cfg = config.get("image_storage", {}) or {}
        use_cos = image_storage_cfg.get("enabled", True) and image_storage_cfg.get("provider") == "picgo"
        on_failure = image_storage_cfg.get("on_failure", "fall_back_local")

        if use_cos:
            # COS 模式: 下载到 temp_dir, 批量 picgo upload, 拿 URL
            temp_dir = Path(image_storage_cfg.get("temp_dir", "/tmp/crawl-images"))
            temp_dir.mkdir(parents=True, exist_ok=True)
        else:
            # 本地模式: 直接下到 vault/media/xhs/ (旧行为)
            media_dir = publisher.subscription_dir.parent / "media" / "xhs"
            media_dir.mkdir(parents=True, exist_ok=True)

        print(f"    Downloading {len(image_urls)} images...")
        temp_paths: List[Path] = []
        for idx, img_url in enumerate(image_urls, 1):
            # 判断扩展名 (XHS URL 通常带 !nc_n_webp_mw_1 等, 但 content-type 是 webp)
            ext = "png"  # mac 老程序都用 .png 后缀
            if ".jpg" in img_url.lower() or "image/jpeg" in img_url.lower():
                ext = "jpg"
            elif ".webp" in img_url.lower() or "_webp" in img_url.lower():
                ext = "webp"

            if use_cos:
                # temp 文件: <uuid>.<ext> (避免重名)
                dest = temp_dir / f"{uuid.uuid4().hex}.{ext}"
            else:
                dest = media_dir / f"{image_date}_{image_time}_{safe_author}_{safe_title_short}_{idx}.{ext}"

            ok = await _download_url_to_file(
                img_url, dest,
                crawler.headers_base.get("User-Agent", DEFAULT_UA),
                "https://www.xiaohongshu.com/",
            )
            if ok and dest.exists() and dest.stat().st_size > 0:
                if use_cos:
                    temp_paths.append(dest)
                    print(f"      [{idx}/{len(image_urls)}] ✅ {dest.stat().st_size} bytes → temp")
                else:
                    rel_path = f"media/xhs/{dest.name}"
                    image_links.append(rel_path)
                    print(f"      [{idx}/{len(image_urls)}] ✅ {dest.stat().st_size} bytes")
            else:
                print(f"      [{idx}/{len(image_urls)}] ❌ download failed")
                if dest.exists():
                    dest.unlink(missing_ok=True)

        # 批量上传到 COS
        if use_cos and temp_paths:
            print(f"    Uploading {len(temp_paths)} images to COS via PicGo...")
            success_urls, failed_paths = picgo_upload_paths(temp_paths)
            for i, url in enumerate(success_urls):
                image_links.append(url)
                print(f"      ✅ {url}")
            for fp in failed_paths:
                if on_failure == "fail":
                    print(f"      ❌ 上传失败 (fail 模式): {fp.name}")
                else:
                    # fall_back_local: 移动到 vault/media/xhs/
                    media_dir = publisher.subscription_dir.parent / "media" / "xhs"
                    media_dir.mkdir(parents=True, exist_ok=True)
                    # 重新生成语义化文件名 (对齐 mac 格式)
                    idx_in_orig = temp_paths.index(fp) + 1  # 在原图列表里的位置
                    ext = fp.suffix.lstrip(".")
                    final_name = f"{image_date}_{image_time}_{safe_author}_{safe_title_short}_{idx_in_orig}.{ext}"
                    final_path = media_dir / final_name
                    try:
                        shutil.move(str(fp), str(final_path))
                        rel_path = f"media/xhs/{final_name}"
                        image_links.append(rel_path)
                        print(f"      ⚠️ 上传失败, 回退到本地: {final_name}")
                    except Exception as e:
                        print(f"      ❌ 本地兜底也失败: {e}")
                        fp.unlink(missing_ok=True)
            # 清理成功上传的 temp 文件
            for tp in temp_paths:
                if tp not in failed_paths:
                    tp.unlink(missing_ok=True)

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
                       note_cards: list = None, douyin_recent_days: int = None):
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
            if douyin_recent_days is None:
                douyin_recent_days = config.get("platforms", {}).get("douyin", {}).get("recent_days", 7)
            print(f"  [douyin] recent_days={douyin_recent_days} (0=全部历史)")
            for author_id in author_ids:
                print(f"\nFetching videos for author: {author_id}")
                videos = await crawler.get_user_videos(sec_user_id=author_id, recent_days=douyin_recent_days)
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
            author_delay = config.get("crawler", {}).get("author_delay", 20)
            xhs_delay = config.get("crawler", {}).get("xhs_request_delay",
                          config.get("crawler", {}).get("request_delay", 5))
            for user_id in author_ids:
                print(f"\nFetching notes for xiaohongshu user: {user_id}")
                try:
                    notes = await crawler.get_user_notes(user_id, num=20)
                except Exception as e:
                    print(f"  Failed to fetch notes: {e}")
                    # 出错也等间隔, 避免快速重试雪崩
                    await asyncio.sleep(author_delay)
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
                            await asyncio.sleep(xhs_delay)
                # 博主之间间隔 (防止连续拉多个博主触发风控)
                if author_ids and user_id != author_ids[-1]:
                    print(f"  [xhs] waiting {author_delay}s before next author...")
                    await asyncio.sleep(author_delay)


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
    parser.add_argument('--douyin-recent-days', type=int, default=None,
                        help='抖音只爬最近 N 天视频 (0=不过滤补历史); 默认读 config.yaml platforms.douyin.recent_days')
    
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
            video_ids=video_ids, author_ids=author_ids,
            douyin_recent_days=args.douyin_recent_days
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
