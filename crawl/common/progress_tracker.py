#!/usr/bin/env python3
"""
crawl/skills 进度监控器
- 实时汇报阶段进度、视频进度、耗时、预计剩余时间
- 每 20 秒自动输出当前状态
- 每个视频/帖子处理完立即更新，watchdog 也跟着刷新
"""
import sys, time, threading, os
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))

# ─── 全局单例 ───────────────────────────────────────────
_tracker = None
_lock = threading.Lock()

class ProgressTracker:
    def __init__(self, total_phases: int, phase_names: list[str]):
        self.phases = phase_names                      # ["抖音", "B站", "小红书", "Boss", "JD", "LinkedIn", "贴吧"]
        self.total_phases = total_phases
        self.current_phase = 0          # 0-indexed
        self.current_blogger = ""
        self.total_items = 0
        self.done_items = 0
        self.start_time = time.time()
        self.phase_start = time.time()
        self.item_start = time.time()
        self._stop = False
        self._items_total_per_phase = {}   # phase -> total (optional, set externally)
        self._thread = threading.Thread(target=self._report_loop, daemon=True)
        self._thread.start()

    # ── 外部调用 ─────────────────────────────────────────
    def set_phase(self, idx: int, blogger_count: int = 0):
        """进入新阶段"""
        with _lock:
            self.current_phase = idx
            self.current_blogger = ""
            self.total_items = 0
            self.done_items = 0
            self.phase_start = time.time()
            self.item_start = time.time()
            pname = self.phases[idx] if idx < len(self.phases) else f"Phase-{idx+1}"
            elapsed = time.time() - self.start_time
            print(f"\n{'='*60}", flush=True)
            print(f"  [{idx+1}/{self.total_phases}] 进入平台: {pname}  (已用时 {fmt_dur(elapsed)})", flush=True)
            if blogger_count:
                print(f"  博主数: {blogger_count}", flush=True)
            print(f"{'='*60}", flush=True)

    def set_blogger(self, name: str, item_count: int = 0):
        """开始处理某博主"""
        with _lock:
            self.current_blogger = name
            self.total_items = item_count
            self.done_items = 0
            self.item_start = time.time()

    def inc_item(self):
        """每个视频/帖子处理完调用"""
        with _lock:
            self.done_items += 1
            self.item_start = time.time()

    def set_total_items(self, n: int):
        with _lock:
            self.total_items = n

    def stop(self):
        self._stop = True

    # ── 后台报告线程 ──────────────────────────────────────
    def _report_loop(self):
        last_phase = -1
        last_blogger = ""
        while not self._stop:
            time.sleep(20)
            with _lock:
                if self._stop:
                    break
                self._print_status()

    def _print_status(self):
        elapsed = time.time() - self.start_time
        phase_elapsed = time.time() - self.phase_start
        item_elapsed = time.time() - self.item_start
        phase_name = self.phases[self.current_phase] if self.current_phase < len(self.phases) else "?"
        p = self.current_phase + 1

        line = f"  [{p}/{self.total_phases}] {phase_name}"
        if self.current_blogger:
            line += f" › {self.current_blogger}"
        if self.total_items > 0:
            pct = self.done_items / self.total_items * 100
            line += f"  {self.done_items}/{self.total_items} ({pct:.0f}%)"
            # 预估剩余时间
            if self.done_items > 0:
                eta_sec = (self.total_items - self.done_items) * (phase_elapsed / max(self.done_items, 1))
                line += f"  ETA {fmt_dur(eta_sec)}"
        else:
            # 2026-07-31 修: total_items=0 + current_blogger 设了 = 该博主 5 个视频全已缓存
            # 之前显示 "0 项已完成" 给监控方错觉"卡了", 改为 "(缓存命中)" 一眼识别
            if self.current_blogger:
                line += f"  (缓存命中)"
            else:
                line += f"  {self.done_items} 项已完成"
        line += f"  | 本阶段 {fmt_dur(phase_elapsed)}  | 总计 {fmt_dur(elapsed)}"
        print(f"  {line}", flush=True)

    def summary(self):
        """全流程结束后打印汇总"""
        total = time.time() - self.start_time
        print(f"\n{'='*60}", flush=True)
        print(f"  全流程耗时: {fmt_dur(total)}", flush=True)
        print(f"  处理: {self.done_items} 个视频/帖子", flush=True)
        print(f"{'='*60}", flush=True)


def fmt_dur(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds/60:.0f}min"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h{m}min"


def init_tracker(phases: list[str]) -> ProgressTracker:
    global _tracker
    with _lock:
        _tracker = ProgressTracker(len(phases), phases)
    return _tracker


def get_tracker() -> ProgressTracker:
    return _tracker
