#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_eagain_retry.py — macOS fork() EAGAIN (Errno 35) 重试工具

背景：macOS 在高并发 fork() 时返回 EAGAIN（Resource temporarily unavailable）。
- 进程级：kern.maxprocperuid 撞上限
- fd 级：ulimit -n 撞上限

用法（替换 subprocess.Popen / subprocess.run）：
    from common_supervisor._eagain_retry import popen_with_retry, run_with_retry
    proc = popen_with_retry(cmd, ...)
    r = run_with_retry(cmd, ...)

策略：
- 捕获 OSError errno=35 (EAGAIN) 时指数退避重试 N 次
- 不影响其他 OSError 行为
"""
import subprocess
import time
from typing import Sequence, Mapping

MAX_RETRIES = 4
BASE_DELAY_SEC = 0.5  # 0.5, 1, 2, 4 秒


def _is_eagain(exc: OSError) -> bool:
    """macOS / Linux 通用：Errno 35 (EAGAIN on macOS, EAGAIN on Linux for non-blocking)
    + Resource temporarily unavailable 错误字符串。"""
    if exc.errno == 35:
        return True
    msg = str(exc).lower()
    return "resource temporarily unavailable" in msg or "errno 35" in msg


def popen_with_retry(
    args: Sequence[str],
    *,
    retries: int = MAX_RETRIES,
    base_delay: float = BASE_DELAY_SEC,
    **popen_kwargs,
):
    """subprocess.Popen 的 EAGAIN-safe 版本。

    其他异常直接抛出，不重试。
    Popen 创建成功后才返回，子进程已启动。
    """
    last_exc = None
    for attempt in range(retries + 1):
        try:
            # macOS 推荐：close_fds=True 减少 fork 后 fd 表大小
            popen_kwargs.setdefault("close_fds", True)
            return subprocess.Popen(args, **popen_kwargs)
        except OSError as e:
            if _is_eagain(e):
                last_exc = e
                if attempt < retries:
                    delay = base_delay * (2 ** attempt)
                    time.sleep(delay)
                    continue
            raise
    # 理论上不会到这，但保险
    raise last_exc  # type: ignore[misc]


def run_with_retry(
    args: Sequence[str],
    *,
    retries: int = MAX_RETRIES,
    base_delay: float = BASE_DELAY_SEC,
    **run_kwargs,
) -> subprocess.CompletedProcess:
    """subprocess.run 的 EAGAIN-safe 版本。

    注意：超时 / CalledProcessError 等其他异常不重试，只重试 fork EAGAIN。
    """
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return subprocess.run(args, **run_kwargs)
        except OSError as e:
            if _is_eagain(e):
                last_exc = e
                if attempt < retries:
                    delay = base_delay * (2 ** attempt)
                    time.sleep(delay)
                    continue
            raise
    raise last_exc  # type: ignore[misc]
