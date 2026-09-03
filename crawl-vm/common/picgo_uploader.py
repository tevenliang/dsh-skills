#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
common/picgo_uploader.py — PicGo CLI 封装

通过 subprocess 调 picgo CLI 把本地图片上传到图床(腾讯云 COS via S3 插件),
返回 URL 列表。失败路径单独返回供调用方兜底。

调用方约定: 传 Path 列表进来, 返回 (success_urls, failed_paths) 元组,
success_urls 和 failed_paths 长度相加 == 输入长度。

设计要点:
- 一次 subprocess 传所有路径 (picgo CLI 支持多文件, 减少启动开销)
- 解析 stdout JSON, 失败的从 returned list 里反推 (按原顺序)
- 异常兜底: subprocess.TimeoutExpired / 非零退出码 → 全部路径视为失败
"""
import json
import shutil
import subprocess
import logging
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)

# 默认 picgo CLI 路径 (dsh-plugin 内置 node_modules 版本)
DEFAULT_PICGO_BIN = "/home/ubuntu/.dsh/profiles/web/node_modules/picgo/bin/picgo"

# 默认超时 (单次 batch, picgo 上传 9 张图 + MD5 + S3 PUT 实测 ~30s, 留 2x 余量)
DEFAULT_TIMEOUT = 180


def _find_picgo() -> str:
    """定位 picgo CLI, 优先 PATH, 找不到就用 dsh-plugin 内置版本"""
    found = shutil.which("picgo")
    if found:
        return found
    if Path(DEFAULT_PICGO_BIN).exists():
        return DEFAULT_PICGO_BIN
    raise FileNotFoundError(
        f"picgo CLI not found in PATH and missing at {DEFAULT_PICGO_BIN}"
    )


def upload_paths(
    paths: List[Path],
    picgo_bin: str = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Tuple[List[str], List[Path]]:
    """批量上传本地文件到图床 (picgo CLI)

    Args:
        paths: 本地文件绝对路径列表
        picgo_bin: picgo CLI 路径 (默认自动定位)
        timeout: 单次调用超时秒数

    Returns:
        (success_urls, failed_paths) 元组, 顺序与输入一致:
        - success_urls[i] 对应 paths[i] 成功后的 URL
        - failed_paths[i] 对应 paths[i] 上传失败, 仍保留本地路径供兜底
        总和 = 输入长度

    Notes:
        - picgo upload 多文件时, stdout 输出一个 JSON 数组: [{"imgUrl":...}, ...]
        - 单文件: stdout 是单 dict {"imgUrl":...}
        - 解析失败/全部失败: 全部路径进 failed_paths
    """
    if not paths:
        return [], []

    # 过滤: 文件必须存在
    valid: List[Path] = []
    failed: List[Path] = []
    for p in paths:
        if p.exists() and p.stat().st_size > 0:
            valid.append(p)
        else:
            failed.append(p)

    if not valid:
        return [], failed

    if picgo_bin is None:
        try:
            picgo_bin = _find_picgo()
        except FileNotFoundError as e:
            logger.error(f"[picgo] {e}")
            return [], list(paths)

    cmd = [picgo_bin, "upload", "--format", "json"] + [str(p) for p in valid]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.error(f"[picgo] 超时 {timeout}s, 全部 {len(valid)} 张视为失败")
        return [], list(paths)
    except Exception as e:
        logger.error(f"[picgo] 调用异常: {type(e).__name__}: {e}")
        return [], list(paths)

    if proc.returncode != 0:
        logger.error(
            f"[picgo] 退出码 {proc.returncode}, stderr: {proc.stderr[:200]}"
        )
        # 返回的输出可能还有部分成功的, 尝试解析
        # 但稳妥起见, 全部视为失败 (picgo 退出非 0 通常整体失败)
        return [], list(paths)

    # 解析 stdout JSON — --format json 模式: stdout 含 INFO 日志 + 末尾一行 JSON 数组
    # JSON 数组在最后一行 ([...]), 顺序与输入文件一致
    stdout = proc.stdout
    if not stdout:
        logger.error("[picgo] stdout 为空, 全部视为失败")
        return [], list(paths)

    # 找最后一个以 '[' 或 '{' 开头的行 (即 JSON 起头)
    json_line = None
    for line in reversed(stdout.splitlines()):
        stripped = line.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            json_line = stripped
            break

    if not json_line:
        logger.error(f"[picgo] stdout 未找到 JSON: {stdout[-200:]}")
        return [], list(paths)

    try:
        result = json.loads(json_line)
    except json.JSONDecodeError:
        logger.error(f"[picgo] JSON 解析失败: {json_line[:200]}")
        return [], list(paths)

    # 单文件: {imgUrl, ...}; 多文件: [{imgUrl, ...}]
    if isinstance(result, dict):
        result_list = [result]
    elif isinstance(result, list):
        result_list = result
    else:
        logger.error(f"[picgo] 未知 JSON 结构: {type(result)}")
        return [], list(paths)

    # 按输入顺序匹配, 失败进 failed_paths
    success_urls: List[str] = []
    failed_paths: List[Path] = list(failed)  # 不存在的先入队

    if len(result_list) != len(valid):
        logger.warning(
            f"[picgo] 返回数量 ({len(result_list)}) != 输入 ({len(valid)}), "
            f"按最长匹配, 多余的视为失败"
        )

    for i, p in enumerate(valid):
        if i < len(result_list) and isinstance(result_list[i], dict):
            url = result_list[i].get("imgUrl") or result_list[i].get("url")
            if url and url.startswith(("http://", "https://")):
                success_urls.append(url)
            else:
                logger.warning(f"[picgo] 第 {i} 项无有效 URL: {result_list[i]}")
                failed_paths.append(p)
        else:
            failed_paths.append(p)

    return success_urls, failed_paths
