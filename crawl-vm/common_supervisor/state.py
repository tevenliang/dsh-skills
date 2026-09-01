#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
state.py — Supervisor ↔ 子进程通信文件
recovery.json: Supervisor 写恢复指令，子进程读它决定行为
status.json:   Supervisor 写当前运行状态，Codex/用户读它了解进度
"""
import json, time, os, threading
from pathlib import Path
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=8))

# 路径
SKILL_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = SKILL_DIR / "state"
STATE_DIR.mkdir(exist_ok=True)

RECOVERY_PATH = STATE_DIR / "recovery.json"
STATUS_PATH   = STATE_DIR / "supervisor.json"
TIMING_PATH   = STATE_DIR / "timing.json"

_lock = threading.Lock()


# ═══════════════════════════════════════════════════════
# recovery.json — Supervisor → 子进程
# ═══════════════════════════════════════════════════════

def _default_recovery() -> dict:
    return {
        "groq":         {"status": "active"},
        "bailian":      {"status": "active", "model": "paraformer-mtl-v1"},
        "mlx":          {"status": "active", "timeout_sec": 300},
        "glm_summary":  {"status": "active", "backoff_until": None},
        "opencli":      {"status": "deprecated"},  # 2026-07-29: 全部走 API，opencli 已弃用
        "last_recovery": None,
    }


def load_recovery() -> dict:
    with _lock:
        if not RECOVERY_PATH.exists():
            return _default_recovery()
        try:
            return json.loads(RECOVERY_PATH.read_text())
        except Exception:
            return _default_recovery()


def save_recovery(data: dict):
    with _lock:
        data["last_recovery"] = datetime.now(TZ).isoformat(timespec="seconds")
        RECOVERY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def is_provider_active(provider: str) -> bool:
    r = load_recovery()
    p = r.get(provider, {})
    if p.get("status") == "disabled":
        return False
    if p.get("status") == "cooldown":
        until = p.get("cooldown_until", 0)
        if time.time() < until:
            return False
        # cooldown 已过，恢复 active
        return True
    return True


def is_glm_backing_off() -> bool:
    r = load_recovery()
    until = r.get("glm_summary", {}).get("backoff_until")
    if not until:
        return False
    return time.time() < float(until)


# ═══════════════════════════════════════════════════════
# status.json — Supervisor → 外接（Codex/用户）
# ═══════════════════════════════════════════════════════

def _default_status() -> dict:
    return {
        "pid": None,
        "started_at": None,
        "last_heartbeat": None,
        "status": "unknown",
        "exit_code": None,
        "phase": None,
        "blogger": None,
        "progress": None,
        "eta": None,
        "total_elapsed": None,
        "last_line": None,
        "last_error": None,
        "stack_dump_path": None,
        "items_done": 0,
        "items_total": 0,
        "provider_states": {},
        "recoveries": [],        # 本次运行的恢复操作记录
    }


def load_status() -> dict:
    with _lock:
        if not STATUS_PATH.exists():
            return _default_status()
        try:
            return json.loads(STATUS_PATH.read_text())
        except Exception:
            return _default_status()


def save_status(data: dict):
    with _lock:
        data["last_heartbeat"] = datetime.now(TZ).isoformat(timespec="seconds")
        STATUS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def update_status(**kwargs):
    s = load_status()
    s.update(kwargs)
    save_status(s)


# ═══════════════════════════════════════════════════════
# timing.json — 耗时统计（合并原分散计时 + Supervisor 新增）
# ═══════════════════════════════════════════════════════

# 关键操作的基准耗时（秒），用于 ETA 计算和异常检测
BENCHMARKS = {
    "fetch_bilibili":   10,    # B站单个视频抓取
    "fetch_douyin":     10,    # 抖音单个视频抓取
    "fetch_xiaohongshu": 15,   # 小红书笔记
    "transcribe_groq":  60,    # Groq 单条（RTF≈0.1，极快）
    "transcribe_bailian": 30,  # Bailian 单条（RTF≈0.02，极快）
    "transcribe_mlx_small": 180,  # MLX small 单条（RTF≈0.37，Mac ANE）
    "transcribe_mlx_medium": 360, # MLX medium 单条（RTF 更低，更慢）
    "summarize_glm":    15,    # GLM 总结单条
    "publish_vault":    5,     # 发布到 vault
    "opencli_op":       60,    # opencli 浏览器操作
}


def _default_timing() -> dict:
    return {
        "run_started_at": None,
        "run_finished_at": None,
        "total_items": 0,
        "total_elapsed_sec": 0,
        "operations": {},      # {op_name: [list of duration_sec]}
        "provider_switches": [],  # [{at, from, to, reason}]
        "errors": [],          # [{at, op, error, severity}]
        "skipped": [],         # [{at, op, reason}]
    }


def load_timing() -> dict:
    with _lock:
        if not TIMING_PATH.exists():
            return _default_timing()
        try:
            return json.loads(TIMING_PATH.read_text())
        except Exception:
            return _default_timing()


def save_timing(data: dict):
    with _lock:
        TIMING_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def record_timing(op_name: str, duration_sec: float, metadata: dict | None = None):
    """记录单次操作耗时（保留 metadata，如 extract_audio 的 download_s/transcode_s）。"""
    data = load_timing()
    ops = data.setdefault("operations", {})
    ops.setdefault(op_name, []).append({"sec": round(duration_sec, 2), "meta": metadata or {}})
    save_timing(data)


def record_error(op_name: str, error_msg: str, severity: str = "MED"):
    data = load_timing()
    data.setdefault("errors", []).append({
        "at": datetime.now(TZ).isoformat(timespec="seconds"),
        "op": op_name,
        "error": error_msg[:200],
        "severity": severity,
    })
    save_timing(data)


def record_provider_switch(from_provider: str, to_provider: str, reason: str):
    data = load_timing()
    data.setdefault("provider_switches", []).append({
        "at": datetime.now(TZ).isoformat(timespec="seconds"),
        "from": from_provider,
        "to": to_provider,
        "reason": reason,
    })
    save_timing(data)


def get_timing_summary() -> dict:
    """返回各操作的平均耗时统计（兼容新旧结构: [float,...] 与 [{"sec","meta"},...]）。

    2026-07-29: 增加 provider_switches 汇总 (总次数 + 按 (from,to) 桶),
    让报告一眼能看出 bailian→mlx / mlx→bailian 等切换链路是否真的命中。
    """
    data = load_timing()
    ops = data.get("operations", {})
    summary = {}
    for op, recs in ops.items():
        if not recs:
            continue
        if isinstance(recs[0], dict):
            secs = [r.get("sec", 0) for r in recs]
        else:
            secs = [float(r) for r in recs]
        summary[op] = {
            "count": len(secs),
            "avg_sec": round(sum(secs) / len(secs), 2),
            "min_sec": round(min(secs), 2),
            "max_sec": round(max(secs), 2),
            "total_sec": round(sum(secs), 2),
        }
    # 2026-07-29: provider_switches 汇总
    switches = data.get("provider_switches", [])
    if switches:
        switch_pairs = {}
        for s in switches:
            key = (s.get("from", "?"), s.get("to", "?"))
            switch_pairs[key] = switch_pairs.get(key, 0) + 1
        summary["__provider_switches__"] = {
            "count": len(switches),
            "by_pair": {f"{a}→{b}": n for (a, b), n in switch_pairs.items()},
        }
    return summary


def get_timing_detail() -> dict:
    """返回各操作完整记录(含 metadata)，供报告展示子段耗时(下载/转码拆分等)。

    结构: {op_name: [{"sec": float, "meta": dict}, ...]}
    """
    data = load_timing()
    return data.get("operations", {})


# ═══════════════════════════════════════════════════════
# 恢复操作工厂
# ═══════════════════════════════════════════════════════

def disable_provider(provider: str, reason: str):
    """永久禁用某 provider。"""
    r = load_recovery()
    r[provider] = {"status": "disabled", "disabled_reason": reason, "disabled_at": datetime.now(TZ).isoformat(timespec="seconds")}
    save_recovery(r)
    # 同时记录 timing
    record_error(provider, reason, "CRIT")
    update_status(provider_states=r.copy())


def set_provider_cooldown(provider: str, seconds: int, reason: str):
    """设置 provider cooldown。"""
    r = load_recovery()
    r[provider] = {
        "status": "cooldown",
        "cooldown_reason": reason,
        "cooldown_until": time.time() + seconds,
    }
    save_recovery(r)
    record_error(provider, f"cooldown {seconds}s: {reason}", "MED")


def set_mlx_degraded(timeout_sec: int = 300):
    """MLX 降级：减少超时限制。"""
    r = load_recovery()
    r["mlx"] = {"status": "degraded", "timeout_sec": timeout_sec}
    save_recovery(r)


def set_glm_backoff(seconds: int, reason: str = "429 rate limit"):
    """GLM 总结退避。"""
    r = load_recovery()
    r["glm_summary"] = {
        "status": "backoff",
        "backoff_reason": reason,
        "backoff_until": time.time() + seconds,
    }
    save_recovery(r)


def restart_opencli():
    """重启 opencli daemon。2026-07-29 deprecated：opencli 已弃用，调用方已切到 bailian/req，仅保留兼容入口。"""
    import subprocess
    r = load_recovery()
    r["opencli"] = {"status": "restarting"}
    save_recovery(r)
    try:
        subprocess.run(["opencli", "daemon", "restart"],
                       capture_output=True, timeout=30)
        r = load_recovery()
        r["opencli"] = {"status": "active", "restarted_at": datetime.now(TZ).isoformat(timespec="seconds")}
        save_recovery(r)
    except Exception as e:
        record_error("opencli", f"restart failed: {e}", "MED")


def reset_recovery():
    """重置所有恢复状态（全流程结束时调用）。"""
    save_recovery(_default_recovery())


def reset_timing():
    """重置耗时统计（新流程开始时调用）。"""
    data = _default_timing()
    data["run_started_at"] = datetime.now(TZ).isoformat(timespec="seconds")
    save_timing(data)
