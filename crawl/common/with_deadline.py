#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
with_deadline() — 通用 deadline 包装器 (2026-07-30 v2)

设计动机: 替代旧 StallMonitor 30min 沉默判定.
  - 旧: 子进程卡住, supervisor 数沉默时间, 30min 才杀 → 黄花菜都凉了
  - 新: 每个 item 内部用 with_deadline() 包住, 超时就放弃当前 item 继续下一个
       supervisor 只在兜底 (子进程内 deadline 都失效) 时才介入

实现机制: 用 daemon thread 跑函数, 主线程 join(timeout).
  - 超时: 函数没跑完, 但 thread 标 daemon=True 随进程退出被回收
  - 不需要 signal handler, 干净
  - 返回 (result, timed_out) 二元组, 调用方决定 fallback

典型用法:
    from common.with_deadline import with_deadline
    
    text, ok = with_deadline(transcribe_sync, args=(wav_path,),
                             kwargs={"model": "..."},
                             deadline_sec=180)
    if not ok:
        deferred.append(item, reason="asr_timeout")
        continue
"""
import threading
import time
from typing import Callable, Tuple, Any


def with_deadline(fn: Callable, args: tuple = (), kwargs: dict | None = None,
                  deadline_sec: float = 60.0) -> Tuple[Any, bool]:
    """同步版 deadline 包装.

    Args:
        fn: 要执行的函数
        args: 位置参数
        kwargs: 关键字参数
        deadline_sec: 超时秒数, 超过返回 (None, False)

    Returns:
        (result, True)  正常完成
        (None, False)   超时
    """
    if kwargs is None:
        kwargs = {}
    holder = {"result": None, "exc": None, "done": False}

    def _runner():
        try:
            holder["result"] = fn(*args, **kwargs)
        except Exception as e:
            holder["exc"] = e
        finally:
            holder["done"] = True

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=deadline_sec)
    if not holder["done"]:
        # 超时: daemon thread 会被随进程退出回收
        return None, False
    if holder["exc"] is not None:
        raise holder["exc"]
    return holder["result"], True


class DeadlineExceeded(Exception):
    """Raise this inside fn if you want to abort early on deadline."""
    pass
