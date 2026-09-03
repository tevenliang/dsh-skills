#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetchers/base.py — clipper-vm fetcher 统一契约与公共工具

契约 (对齐 Mac tools/<plat>.crawl):
  fetcher.crawl(url, tmp_dir, config) → (title, author, md_path, images_dir)
    - title: 标题 (str)
    - author: 作者 (str，可为空)
    - md_path: 生成的 markdown 文件路径 (str)
    - images_dir: 图片目录路径 (str，无图可为空 str)
  fetcher 抛异常或返回 (None, None, None, None) 表示处理失败/跳过

注意: fetcher 只负责"抓取并生成 md"，转录/总结/发布由 clip.py 主流程完成。
视频类平台 (douyin/bilibili) 的 md 里转录文本为空 (transcript_pending: true)，
由主流程下载音频→转录后填充。
"""
import asyncio
import subprocess
from pathlib import Path


# 支持平台 (对齐 Mac URL_PLATFORMS)
URL_PLATFORMS = {"bilibili", "douyin", "xiaohongshu", "generic", "wechat"}

# 需要 LLM 总结的平台 (对齐 Mac SUMMARIZE_PLATFORMS; xhs 用户关闭了总结)
SUMMARIZE_PLATFORMS = {"bilibili", "douyin", "generic"}


def download_url_to_file(url: str, dest: Path, user_agent: str, referer: str,
                         timeout: int = 180, connect_timeout: int = 30,
                         proxy: str = "") -> bool:
    """下载 URL 到文件 (curl subprocess)"""
    cmd = [
        "curl", "-s", "-L", "-o", str(dest),
        "--connect-timeout", str(connect_timeout),
        "--max-time", str(timeout),
        "-A", user_agent,
        "-H", f"Referer: {referer}",
    ]
    if proxy:
        cmd += ["--proxy", proxy]
    cmd.append(url)
    try:
        r = subprocess.run(cmd, timeout=timeout + 20)
        return r.returncode == 0 and dest.exists() and dest.stat().st_size > 0
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False


async def async_download_url_to_file(url: str, dest: Path, user_agent: str, referer: str,
                                     timeout: int = 180, proxy: str = "") -> bool:
    """async 包装 download_url_to_file (curl 阻塞调用放到线程池)"""
    return await asyncio.to_thread(
        download_url_to_file, url, dest, user_agent, referer, timeout, 30, proxy)