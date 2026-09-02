#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
supervisor.py — ominicrawl 主动监护主程序
取代 run.sh 直接调用 crawl.py，包装为被监控子进程。

职责:
1. 启动并守护 crawl.py 子进程
2. 实时解析子进程 stdout/stderr，匹配异常模式
3. 主动干预（降级/重启/切换 provider）
4. 检测断流（5min 警告/15min 降级/30min 终止）
5. 维护 status.json 供 Codex 轮询

OP 耗时由跑批结束后解析日志生成，不在 supervisor 内计时。

用法:
  supervisor.py --sub <crawl.py 路径> [crawl 参数...]
  supervisor.py --status          # 只读状态
"""
import argparse
import os
import re
import select
import signal
import subprocess
import json
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 兼容 crawl skill 的 _bootstrap 路径机制
_here = Path(__file__).parent
while _here and not (_here / "_bootstrap.py").exists():
    _p = _here.parent
    if _p == _here:
        _here = None
        break
    _here = _p
if _here:
    sys.path.insert(0, str(_here))
import _bootstrap


SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))
sys.path.insert(0, str(SKILL_DIR / "common"))
# crawl-vm 不再依赖 common-asr, ASR 在 common/transcribe.py 中

from common_supervisor.state import (
    load_recovery,
    RECOVERY_PATH, STATUS_PATH,
    load_status, save_status, update_status,
    load_timing,  # 仅用于 _print_summary 读 errors
    record_error, record_provider_switch,
    reset_recovery,
)
from common_supervisor.recovery import react, react_lines, reset_counts
from common_supervisor.patterns import Severity
from common_supervisor import run_meta

TZ = timezone(timedelta(hours=8))

# (STALL_* 常量已删 - 2026-07-30 v2 重设计: 由 ActionMonitor 接管)

# 进度行解析正则（从 ProgressTracker 输出提取 phase/blogger/progress/eta）
PROGRESS_RE = re.compile(
    r"\[(\d+)/(\d+)\]\s+(\S+)(?:\s*›\s*(\S+))?\s+(\d+)/(\d+)\s+\((\d+)%\)\s*(?:ETA\s+(\S+))?\s*\|\s*本阶段\s+(\S+)\s*\|\s*总计\s+(\S+)"
)
PROGRESS_SIMPLE_RE = re.compile(r"\[(\d+)/(\d+)\]\s+进入平台:\s*(\S+)")
PROGRESS_ITEM_RE = re.compile(r"🌐 \[(\S+)\]")
PROGRESS_SUMMARY_RE = re.compile(r"全流程耗时[:：]\s*(\S+)")


# ═══════════════════════════════════════════════════════
# ActionMonitor — 替代 StallMonitor (2026-07-30 v2)
# ═══════════════════════════════════════════════════════

class ActionMonitor:
    """Per-action 进度监护 (取代全局沉默判定).

    设计: 跟当前 active item 的 [phase, blogger, idx] 配合,
    唯一判定"卡死"的标准 = active item 持续 > grace_sec 无变化.
    阈值可通过 config.yaml action_monitor.* 调整.
    """

    def __init__(self, sub_proc, tag: str, grace_sec: int = 600, poll_sec: int = 30):
        self._sub_proc = sub_proc
        self._tag = tag
        self._grace_sec = grace_sec
        self._poll_sec = poll_sec
        self._last_signature = None   # (phase, blogger, done, total)
        self._last_change = time.time()
        self._stop = False
        self._kill_done = False
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def touch(self, prog: dict | None):
        """主循环每次解析到进度行时调用."""
        if not prog:
            return
        sig = (prog.get("phase"), prog.get("blogger"), prog.get("progress"))
        with self._lock:
            if sig != self._last_signature:
                self._last_signature = sig
                self._last_change = time.time()

    def stop(self):
        self._stop = True

    def _run(self):
        while not self._stop:
            time.sleep(self._poll_sec)
            if self._kill_done:
                continue
            with self._lock:
                gap = time.time() - self._last_change
            if gap <= self._grace_sec:
                continue
            # 超过 grace_sec 仍未变化 + 子进程还活着 → 杀
            if self._sub_proc.poll() is None:
                active_dur = int(gap)
                run_meta.append_event(self._tag, "sub_process_killed",
                                      reason=f"active item unchanged for {active_dur}s",
                                      active_signature=str(self._last_signature))
                record_error("action_monitor",
                             f"kill sub-process: active unchanged {active_dur}s",
                             "CRIT")
                try:
                    self._sub_proc.terminate()
                except Exception:
                    pass
                self._kill_done = True


# ═══════════════════════════════════════════════════════


# 操作阶段识别（从 stdout 行识别当前在做什么）
OP_PATTERNS = [
    (re.compile(r"🌐 \[(bilibili|douyin)\]"), "fetch"),  # crawl-vm 暂只支持 douyin/bilibili
    (re.compile(r"\[transcribe\].*?(?:Success|Failed)"), "transcribe_groq"),
    (re.compile(r"\[summarize\].*?(?:Success|Failed)"), "summarize"),
    (re.compile(r"\[start\].*?'platform':"), "fetch"),
    (re.compile(r"\[skipped\]"), "skip_dedup"),
    (re.compile(r"\[success\]"), "publish_vault"),
    (re.compile(r"\[failed\]"), "fetch"),
]

# 每个操作的计时器（start time）
def _parse_progress(line: str) -> dict | None:
    """从 ProgressTracker 输出行提取结构化进度。"""
    m = PROGRESS_RE.search(line)
    if m:
        p_cur, p_total, phase, blogger, done, total, pct, eta, phase_elapsed, total_elapsed = m.groups()
        return {
            "phase": phase,
            "blogger": blogger or "",
            "progress": f"{done}/{total} ({pct}%)",
            "eta": eta or "",
            "phase_elapsed": phase_elapsed,
            "total_elapsed": total_elapsed,
        }
    m = PROGRESS_SIMPLE_RE.search(line)
    if m:
        p_cur, p_total, phase = m.groups()
        return {"phase": phase, "progress": None, "blogger": None, "eta": None, "phase_elapsed": None, "total_elapsed": None}
    return None

# ═══════════════════════════════════════════════════════
# 断流检测线程
# ═══════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════
# 主监督循环
# ═══════════════════════════════════════════════════════

def run_supervised(sub_cmd: list[str], extra_env: dict | None = None, reset: bool = True, run_tag: str | None = None):
    """启动子进程并监督。

    Args:
        reset: 是否在入口重置 timing.json / recovery.json / status.json。
               cmd_all() 串行调用 watchlist → clip 时，clip 阶段需要 reset=False，
               否则 watchlist 阶段写入的 provider_switches / operations 会被洗掉。
    """
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if extra_env:
        env.update(extra_env)

    # 修 #2 (2026-07-30): reset_recovery/reset_counts 必须在 spawn 子进程之前完成,
    # 否则子进程启动后会立刻读到上一轮残留的 disabled_reason, 跳过所有 provider.
    if reset:
        reset_counts()
        reset_recovery()

    # 一个 all 跑批共享同一个 run_tag；单阶段调用则自行生成。
    run_tag = run_tag or run_meta.make_run_tag()
    env["CRAWL_RUN_TAG"] = run_tag
    paths = run_meta.tag_paths(run_tag)
    phase = "clip" if "clip" in sub_cmd else "watchlist"
    run_meta.append_event(run_tag, "phase_started", phase=phase)
    run_meta.append_event(run_tag, "sub_process_spawning", cmd=sub_cmd)

    # 启动子进程（独立进程组, macOS fork EAGAIN 重试）
    from common_supervisor._eagain_retry import popen_with_retry as _popen_retry
    proc = _popen_retry(
        sub_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,   # stderr 合并到 stdout
        text=True,
        bufsize=1,                  # 行缓冲
        start_new_session=True,
        env=env,
    )

    start_time = time.time()

    # 2026-07-30 v2: 把 run_tag 写入状态 (用真实子进程 pid)
    run_meta.append_event(run_tag, "sub_process_started",
                          pid=proc.pid, cmd=sub_cmd)

    save_status({
        "run_tag": run_tag,
        "pid": proc.pid,
        "started_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "last_heartbeat": datetime.now(TZ).isoformat(timespec="seconds"),
        "status": "running",
        "exit_code": None,
        "phase": None,
        "blogger": None,
        "progress": None,
        "eta": None,
        "total_elapsed": None,
        "last_line": None,
        "last_error": None,
        "items_done": 0,
        "items_total": 0,
        "provider_states": load_recovery().copy(),
        "recoveries": [],
    })

    total_items = 0

    print(f"\n{'='*60}", flush=True)
    print(f"  [Supervisor] 启动 PID={proc.pid}  run_tag={run_tag}", flush=True)
    print(f"  events:  {paths['events']}", flush=True)
    print(f"  log:     {paths['log_out']}", flush=True)
    print(f"  {'='*60}\n", flush=True)

    # ActionMonitor 启动 (替代 StallMonitor)
    action_monitor = ActionMonitor(proc, tag=run_tag, grace_sec=1800, poll_sec=30)  # 2026-08-08: 600→1800, 大视频 mlx 转录可达 30min, 看门狗误杀


    # 行缓冲读取器（兼容 select.select）
    line_buf = []

    try:
        while True:
            # 用 select 监听 stdout，超时用于定期检查断流
            ready, _, _ = select.select([proc.stdout], [], [], 30)
            if not ready:
                # 超时：断流检测线程在跑，这里只做快速状态更新
                update_status(
                    total_elapsed=_fmt_dur(time.time() - start_time),
                )
                continue

            line = proc.stdout.readline()
            if not line:
                # 子进程 stdout 关闭，检查是否真的退出了
                if proc.poll() is not None:
                    break
                continue

            line = line.rstrip("\n")
            if not line.strip():
                continue

            # ── 打印到终端 ──────────────────────────────────────────────
            print(line, flush=True)

            # ── heartbeat: 只要子进程有输出就刷新, 方便外部轮询 supervisor --status ──
            update_status(last_line=line[:200])

            # ── 进度解析 ────────────────────────────────────────────────
            # ── 进度解析 (PROGRESS_RE / PROGRESS_SUMMARY_RE) ──
            prog = _parse_progress(line)
            if prog:
                update_status(**prog)
                action_monitor.touch(prog)  # 2026-07-30 v2: 通知 ActionMonitor 进度变了
            m = PROGRESS_SUMMARY_RE.search(line)
            if m:
                update_status(
                    total_elapsed=m.group(1),
                    status="finishing",
                )

            # ── crawl-vm 简单事件解析 ([start]/[skipped]/[success]/[failed]) ──
            for ev_re, ev_key in (
                (re.compile(r"\[start\]\s+\{'platform':\s*'(\w+)'"), "phase"),
                (re.compile(r"\[start\]\s+\{'platform':\s*'(\w+)',\s*'video_id'"), "item"),
                (re.compile(r"\[skipped\]"), "skip"),
                (re.compile(r"\[success\]"), "success"),
                (re.compile(r"\[failed\]"), "failed"),
            ):
                m2 = ev_re.search(line)
                if m2:
                    if ev_key == "phase":
                        update_status(phase=m2.group(1))
                        action_monitor.touch({"phase": m2.group(1), "blogger": None, "progress": None})
                    elif ev_key == "item":
                        update_status(phase=m2.group(1))
                        action_monitor.touch({"phase": m2.group(1), "blogger": None, "progress": "1"})
                    elif ev_key == "success":
                        update_status(items_done=(load_status().get("items_done", 0) + 1))
                        action_monitor.touch({"phase": None, "blogger": None, "progress": "success"})
                    elif ev_key == "skip":
                        action_monitor.touch({"phase": None, "blogger": None, "progress": "skip"})
                    break

            # ── 转录计时解析: [transcribe] Groq success: N chars (Xs) ────────
            # 格式: [transcribe] Groq success: 504 chars (3.2s)
            #       [transcribe] bailian success: 843 chars (8.1s)
            _tm = re.search(r"\[transcribe\]\s+(Groq|bailian)\s+success:\s+\d+\s+chars\s+\(([\d.]+)s\)", line)
            if _tm:
                _provider = _tm.group(1).lower()  # "groq" or "bailian"
                _elapsed = float(_tm.group(2))
                from state import record_timing
                record_timing(f"transcribe_{_provider}", _elapsed, {"ok": True})

            # ── 异常模式匹配 + 恢复决策 ──────────────────────────────────
            action = react(line)
            if action:
                print(f"\n  🔧 [Supervisor] {action}\n", flush=True)
                # 追加到 recoveries
                s = load_status()
                s.setdefault("recoveries", []).append({
                    "at": datetime.now(TZ).isoformat(timespec="seconds"),
                    "action": action,
                    "line": line[:200],
                })
                save_status(s)
                record_error("supervisor_action", action, "MED")

    except KeyboardInterrupt:
        print("\n  [Supervisor] Ctrl+C，等待子进程优雅退出...", flush=True)
        proc.terminate()
        proc.wait(timeout=30)
        update_status(status="interrupted", exit_code=-1, last_error="KeyboardInterrupt")
        return -1

    # ── 等待子进程真正退出 ─────────────────────────────────────────────────
    exit_code = proc.wait()

    total_elapsed = time.time() - start_time

    # 写最终状态
    run_meta.append_event(run_tag, "sub_process_exited",
                          phase=phase, exit_code=exit_code,
                          total_elapsed_sec=round(total_elapsed, 1))
    run_meta.append_event(run_tag, "phase_finished", phase=phase, exit_code=exit_code,
                          duration_sec=round(total_elapsed, 1))
    save_status({
        "status": "exited_ok" if exit_code == 0 else "exited_error",
        "exit_code": exit_code,
        "total_elapsed": _fmt_dur(total_elapsed),
        "last_heartbeat": datetime.now(TZ).isoformat(timespec="seconds"),
    })

    action_monitor.stop()

    # 2026-07-30: 父进程在子进程退出后才写 timing.json。
    # 时序：子进程先退出 → 父进程接管 stdout 管道 → 读完剩余输出 → 才写 timing.json。
    # 这样不会覆盖子进程的数据（子进程已不在运行）。
    # total_items 由 report 阶段从日志解析的 ASR 次数推算。
    # 所有耗时数据由 parse_timing_truth.py 从日志文件解析，作为唯一真实数据源。
    # timing 全量记录已迁移到日志解析管道
    # total_elapsed_sec 和 total_items 已在 run_supervised 退出后由 wall clock 计算



    # ── 打印汇总 ───────────────────────────────────────────────────────────
    _print_summary(exit_code, total_elapsed)

    return exit_code

def _fmt_dur(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds/60:.0f}min"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h{m}min"

def _print_summary(exit_code: int, total_elapsed: float):
    """运行结束汇总（不含 timing，timing 已迁移到日志解析管道）。"""
    print(f"\n{'='*60}", flush=True)
    print(f"  [Supervisor] 全流程结束", flush=True)
    print(f"  退出码: {exit_code}", flush=True)
    print(f"  总耗时: {_fmt_dur(total_elapsed)}", flush=True)

    s = load_status()
    recoveries = s.get("recoveries", [])
    if recoveries:
        print(f"\n  本次恢复操作 ({len(recoveries)} 次):", flush=True)
        for r in recoveries:
            print(f"    [{r['at'][11:]}] {r['action']}", flush=True)

    errors = load_timing().get("errors", [])
    if errors:
        print(f"\n  错误记录 ({len(errors)} 条):", flush=True)
        for e in errors[-5:]:
            print(f"    [{e['at'][11:]}] [{e['severity']}] {e['op']}: {e['error'][:80]}", flush=True)

    print(f"{'='*60}\n", flush=True)

def cmd_status():
    """只读当前状态。"""
    s = load_status()
    if not s or s.get("status") == "unknown":
        print("Supervisor 未运行")
        return
    print(f"状态: {s.get('status')}")
    print(f"PID: {s.get('pid')}")
    print(f"启动: {s.get('started_at')}")
    print(f"阶段: {s.get('phase', '?')}")
    print(f"进度: {s.get('progress', '?')}")
    print(f"已用时: {s.get('total_elapsed', '?')}")
    print(f"最后输出: {s.get('last_line', '?')[:100] if s.get('last_line') else '?'}")
    print(f"恢复操作: {len(s.get('recoveries', []))} 次")
    print(f"Provider 状态:")
    for p, v in s.get("provider_states", {}).items():
        if not isinstance(v, dict):
            print(f"  {p}: {v}")
            continue
        print(f"  {p}: {v.get('status')} {v.get('disabled_reason', '')}".strip())


def preflight_check(skill: str, py: str) -> bool:
    """爬取前健康检查（crawl-vm 简化版）.

    crawl-vm 只需要 3 项检查:
    1. VPN 代理 (127.0.0.1:7890) 连通
    2. Groq API key 可用
    3. Vault 目录可写

    Returns:
        bool: True 全部通过, False 有致命问题（应退出）
    """
    import subprocess
    from pathlib import Path
    skill_path = Path(skill)
    print("=" * 60)
    print("🔍 preflight 检查 (crawl-vm)")
    print("=" * 60)
    fatal = False

    # 1. VPN 代理
    print("\n[1/3] VPN 代理 (127.0.0.1:7890)")
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        r = s.connect_ex(('127.0.0.1', 7890))
        s.close()
        if r == 0:
            print("  ✅ VPN 代理端口可达")
        else:
            print(f"  ❌ VPN 代理不可达 (errno={r}), 爬虫无法访问外网")
            fatal = True
    except Exception as e:
        print(f"  ❌ VPN 代理检测失败: {e}")
        fatal = True

    # 2. Groq key
    print("\n[2/3] Groq API key")
    try:
        # crawl-vm 用简化版: 只检查 key 文件存在 + 内容非空
        import json
        key_file = Path.home() / ".agents" / "credentials" / "ominicrawl" / "groq.json"
        if key_file.exists():
            try:
                key_data = json.loads(key_file.read_text())
                key = key_data.get("api_key", "")
                if key and key.startswith("gsk_"):
                    print("  ✅ Groq key 可用")
                else:
                    print("  ❌ Groq key 文件格式异常")
                    fatal = True
            except Exception as e:
                print(f"  ❌ Groq key 文件解析失败: {e}")
                fatal = True
        else:
            print(f"  ❌ Groq key 文件不存在: {key_file}")
            fatal = True
    except Exception as e:
        print(f"  ⚠️ Groq 检测失败: {e}")
        fatal = True

    # 3. Vault 目录可写
    print("\n[3/3] Vault 目录")
    vault = skill_path / "vault"
    if not vault.exists():
        # crawl-vm 配置指向 webdav，不一定在 skill_path 下
        # 改成检查状态目录
        vault = Path("/home/ubuntu/webdav/steven_vault")
    vault_parent = vault.parent
    if vault_parent.exists() and vault_parent.is_dir():
        try:
            test_file = vault_parent / ".supervisor_test"
            test_file.write_text("ok")
            test_file.unlink()
            print(f"  ✅ Vault 父目录可写: {vault_parent}")
        except Exception as e:
            print(f"  ❌ Vault 父目录不可写: {e}")
            fatal = True
    else:
        print(f"  ❌ Vault 父目录不存在: {vault_parent}")
        fatal = True

    print("\n" + "=" * 60)
    if fatal:
        print("❌ preflight 有致命问题，建议先修复再跑")
    else:
        print("✅ preflight 通过")
    print("=" * 60)
    return not fatal

def cmd_all(date: str, py: str, skill: str):
    """crawl-vm 一气呵成: 跑 platform(s) → 生成 daily index。

    流程:
    - Step 0: preflight (VPN / Groq / Vault)
    - Step 1: pipeline.run (走 supervisor 内嵌, 守护 + 自动 kill 卡死)
    """
    import subprocess
    from pathlib import Path
    skill_path = Path(skill)
    run_py = skill_path / "pipeline" / "run.py"

    if not run_py.exists():
        print(f"❌ 找不到 {run_py}")
        return 1

    run_tag = run_meta.make_run_tag()
    run_meta.append_event(run_tag, "run_started", date=date)
    print("=" * 60)
    print(f"📦 crawl-vm all 流程 - 日期: {date} run_tag={run_tag}")
    print("=" * 60)

    # Step 0: preflight
    preflight_ok = preflight_check(skill, py)
    if not preflight_ok:
        print("❌ preflight 有致命问题, 拒绝跑批")
        return 1

    # Step 1: pipeline.run (带 supervisor 守护)
    print(f"\n[1/2] 🚀 启动 pipeline.run\n")
    rc = run_supervised([py, "-m", "pipeline.run", "--platforms", "all", "--date", date],
                        run_tag=run_tag)

    run_meta.append_event(run_tag, "run_finished", exit_code=rc)

    print(f"\n[2/2] 📊 收尾 (pipeline.run 已自动生成 daily index)")

    return rc


def main():
    parser = argparse.ArgumentParser(prog="supervisor.py",
                                     description="crawl-vm 主动监护主程序")
    parser.add_argument("--sub", nargs=argparse.REMAINDER, dest="sub_cmd",
                        help="子进程命令（supervisor.py --sub python -m pipeline.run）")
    parser.add_argument("--status", action="store_true",
                        help="只读状态文件")
    parser.add_argument("--reset", action="store_true",
                        help="重置所有状态文件（恢复初始）")
    parser.add_argument("--all", nargs="?", const="today", default=None,
                        help="一气呵成：preflight → pipeline.run → index（推荐入口）")
    parser.add_argument("--py", default=None, help="Python 解释器路径（--all 用）")
    parser.add_argument("--skill", default=None, help="Skill 根路径（--all 用）")
    args = parser.parse_args()

    if args.status:
        cmd_status()
        return


    if args.reset:
        reset_recovery()
        save_status({"status": "unknown"})
        print("已重置")
        return

    if args.all:
        from datetime import datetime
        date = args.all if args.all != "today" else datetime.now().strftime("%Y%m%d")
        py = args.py or sys.executable
        skill = args.skill or str(Path(__file__).resolve().parent.parent)
        return cmd_all(date, py, skill)

    if not args.sub_cmd:
        parser.print_help()
        return

    exit_code = run_supervised(args.sub_cmd)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
