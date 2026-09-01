#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_meta.py — 每次跑批的 run_tag + 结构化事件日志 (2026-07-30 v2)

设计:
  - run_tag = run_<YYYYMMDD>_<HHMMSS>_<PID>   (唯一一次跑批)
  - state/run_<tag>.events.jsonl   每条一行 JSON, append-only
      {"ts":..., "event":"item_done", ...}
  - state/run_<tag>.status.json    当前快照 (兼容 state.supervisor.json)
  - state/run_<tag>.recovery.json  provider cooldown 状态

OP 报告改读 events.jsonl + status.json, 不再 parse stdout.
"""
import json
import os
import time
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
SKILL_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = SKILL_DIR / "state"
STATE_DIR.mkdir(exist_ok=True, parents=True)

_lock = threading.Lock()


def make_run_tag(pid: int | None = None) -> str:
    """生成唯一 run_tag, 例 run_20260730_223015_73521"""
    now = datetime.now(TZ)
    p = pid or os.getpid()
    return f"run_{now.strftime('%Y%m%d_%H%M%S')}_{p}"


def tag_paths(tag: str) -> dict:
    """返回 tag 对应的所有文件路径"""
    return {
        "events":   STATE_DIR / f"{tag}.events.jsonl",
        "status":   STATE_DIR / f"{tag}.status.json",
        "recovery": STATE_DIR / f"{tag}.recovery.json",
        "log_out":  SKILL_DIR / "logs" / f"{tag}.out",
        "log_err":  SKILL_DIR / "logs" / f"{tag}.err",
    }


def list_recent_tags(n: int = 10) -> list[str]:
    """列最近 n 个 run_tag (按时间倒序)"""
    out = []
    for p in sorted(STATE_DIR.glob("run_*.events.jsonl"), reverse=True):
        out.append(p.name.replace(".events.jsonl", ""))
        if len(out) >= n:
            break
    return out


def append_event(tag: str, event: str, **kwargs) -> None:
    """追加一条事件到 events.jsonl (append-only)"""
    path = tag_paths(tag)["events"]
    rec = {
        "ts": datetime.now(TZ).isoformat(timespec="seconds"),
        "event": event,
    }
    rec.update(kwargs)
    with _lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def save_status_for(tag: str, status: dict) -> None:
    """写入 status 快照"""
    path = tag_paths(tag)["status"]
    with _lock:
        status["last_heartbeat"] = datetime.now(TZ).isoformat(timespec="seconds")
        path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def load_status_for(tag: str) -> dict:
    """读 status 快照"""
    path = tag_paths(tag)["status"]
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_recovery_for(tag: str, recovery: dict) -> None:
    path = tag_paths(tag)["recovery"]
    with _lock:
        path.write_text(json.dumps(recovery, ensure_ascii=False, indent=2), encoding="utf-8")


def load_recovery_for(tag: str) -> dict:
    path = tag_paths(tag)["recovery"]
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def events_to_ops(tag: str) -> dict:
    """从 events.jsonl 聚合出每 op 的次数/耗时 (供 OP 报告用).

    返回: {op_name: [{"sec": float, "meta": dict}, ...]}
    """
    path = tag_paths(tag)["events"]
    if not path.exists():
        return {}
    ops = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            ev = rec.get("event", "")
            op = None
            sec = rec.get("duration_sec")
            if ev == "phase_done":
                op = rec.get("phase")
            elif ev == "item_done":
                continue
            if not op:
                continue
            ops.setdefault(op, []).append({"sec": sec or 0.0, "meta": rec})
    return ops
