#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 OP 环节生成 crawl 跑批报告。

报告分 5 张表（按 OP pipeline 真实链路）：
  OP-1 fetch        : discovery / ingested / by platform
  OP-2 classify     : video_with_transcript / video_asr_failed / image_post
  OP-3 download     : extract_audio 次数 / 耗时（来自日志 timing）
  OP-4 transcribe   : groq / bailian / mlx 成功+失败 / 耗时（来自日志 timing）
  OP-5 summarize    : summary_glm done / skip（来自日志）

vault 真实分类 = 事后扫描 ~/Documents/steven_vault/subscription/**/2026-07-29_*.md
  - source_url 含 /video/  → 视频
  - body 含 "## 转录 " 段（兼容 带/不带 "(来源: xxx)"）→ ASR 成功
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

SKILL = Path(__file__).resolve().parent
VAULT = Path("/Users/tianwenliang/Documents/steven_vault")
REPORT_DIR = VAULT / "04_agent/report"
LOG_DIR = SKILL / "logs"
TRUTH_PATH = SKILL / "state/truth.json"
SUBSCRIPTION = VAULT / "subscription"
TZ = timezone(timedelta(hours=8))


# ─── 日期 ──────────────────────────────────────────────
def _normalize_date(value: str | None) -> tuple[str, str, str]:
    raw = value or datetime.now(TZ).strftime("%Y%m%d")
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 4:
        digits = datetime.now(TZ).strftime("%Y") + digits
    if len(digits) != 8:
        raise ValueError(f"日期格式错误: {raw}, 应为 MMDD 或 YYYYMMDD")
    return digits, digits[4:], f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"


def _find_log(full_date: str, mmdd: str) -> Path:
    direct = [LOG_DIR / f"launchd_{full_date}.out", LOG_DIR / f"launchd_{mmdd}.out"]
    for path in direct:
        if path.exists() and path.stat().st_size:
            return path

    target_file_date = f"{full_date[:4]}-{full_date[4:6]}-{full_date[6:]}_"
    candidates: list[Path] = []
    for path in LOG_DIR.glob("launchd_*.out"):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if target_file_date in text or full_date in text:
                candidates.append(path)
        except OSError:
            continue
    if candidates:
        return max(candidates, key=lambda p: p.stat().st_mtime)
    raise FileNotFoundError(f"找不到跑批日志: {LOG_DIR}/launchd_*.out")



# ─── v2 (2026-07-30): 直接读 events.jsonl, 不再 parse stdout ─────
def _find_latest_run_tag() -> str | None:
    """从 state/run_*.events.jsonl 找最近一个 run_tag"""
    runs = sorted(STATE_DIR.glob("run_*.events.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not runs:
        return None
    return runs[0].name.replace(".events.jsonl", "")


def _parse_run_tag(tag: str) -> dict:
    """从 events.jsonl 聚合出 OP 报告需要的数据结构.

    返回与 _parse_latest_run() 同构的 dict, 便于下游 build_op_report 复用:
    {
      "operations": {op_name: [{"sec": float, "meta": dict}, ...]},
      "provider_switches": [...],
      "errors": [...],
      "skipped": [...],
      "run_tag": str,
      "total_items": int,
      "total_elapsed_sec": float,
    }
    """
    events_path = STATE_DIR / f"{tag}.events.jsonl"
    status_path = STATE_DIR / f"{tag}.status.json"
    if not events_path.exists():
        raise FileNotFoundError(f"events.jsonl 不存在: {events_path}")

    operations: dict = {}
    provider_switches: list = []
    errors: list = []
    item_done_count = 0
    item_total = 0
    total_elapsed_sec = 0.0
    started_at = None
    exited_at = None
    killed = False

    with open(events_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            ev = rec.get("event", "")
            if ev == "item_done":
                item_done_count += 1
                dur = rec.get("duration_sec") or 0
                op = "item_done"
                operations.setdefault(op, []).append({"sec": float(dur), "meta": rec})
            elif ev == "item_start":
                item_total = max(item_total, rec.get("item_total", 0))
            elif ev == "sub_process_started":
                started_at = rec.get("ts")
            elif ev == "sub_process_exited":
                exited_at = rec.get("ts")
                total_elapsed_sec = rec.get("total_elapsed_sec", 0)
            elif ev == "sub_process_killed":
                killed = True
                errors.append({
                    "at": rec.get("ts", ""),
                    "op": "action_monitor",
                    "error": rec.get("reason", ""),
                    "severity": "CRIT",
                })

    # provider_switches / asr 分类: 暂留空, 待 v2 完整接入
    return {
        "run_tag": tag,
        "operations": operations,
        "provider_switches": provider_switches,
        "errors": errors,
        "skipped": [],
        "total_items": item_done_count,
        "total_elapsed_sec": total_elapsed_sec,
        "started_at": started_at,
        "exited_at": exited_at,
        "killed": killed,
    }


# ─── v1 (旧): 仍兼容 log 解析 (truth.json 兜底) ─────────
def _parse_latest_run(log_path: Path) -> dict:
    proc = subprocess.run(
        [
            sys.executable,
            str(SKILL / "scripts/parse_timing_truth.py"),
            str(log_path),
            "--latest-run",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(proc.stderr.strip() or "OP 日志解析失败")
    data = json.loads(proc.stdout)
    TRUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRUTH_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


# ─── vault 真实分类 (事后扫描, 取代"靠日志成功行计数") ──────────
def _scan_vault(date_iso: str) -> dict:
    """扫描 vault 当日入库的 md, 分类视频/图文/ASR状态.

    Returns:
        {
            "total_published": int,
            "by_platform": {platform: count},
            "video_total": int,
            "video_with_transcript": int,
            "video_asr_failed": int,
            "image_total": int,
            "video_failed_paths": [path, ...],   # 视频但 ASR 失败的 md (用于重试)
        }
    """
    pattern = f"{date_iso}_"
    by_platform: Counter = Counter()
    video_total = 0
    video_with_transcript = 0
    video_asr_failed = 0
    image_total = 0
    video_failed_paths: list[str] = []
    total_published = 0

    for path in SUBSCRIPTION.rglob(f"*{pattern}*.md"):
        if not path.is_file():
            continue
        total_published += 1
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # 提取 platform: 从路径 /subscription/<plat>/<author>/...
        rel = path.relative_to(SUBSCRIPTION)
        plat = rel.parts[0] if len(rel.parts) > 1 else "unknown"
        # 跳过 monthly index / hot index
        if path.name.endswith("-hot.md") or "_index.md" in str(path):
            continue
        by_platform[plat] += 1

        # 解析 source_url 是否含 /video/
        is_video = "/video/" in text
        # 正文是否含 "## 转录" 段
        has_transcript_section = ("\n## 转录\n" in text or "\n## 转录 (" in text)

        if is_video:
            video_total += 1
            if has_transcript_section:
                video_with_transcript += 1
            else:
                video_asr_failed += 1
                video_failed_paths.append(str(path))
        else:
            image_total += 1

    return {
        "total_published": total_published,
        "by_platform": dict(by_platform),
        "video_total": video_total,
        "video_with_transcript": video_with_transcript,
        "video_asr_failed": video_asr_failed,
        "image_total": image_total,
        "video_failed_paths": video_failed_paths,
    }


def _secs(records: list) -> list[float]:
    result: list[float] = []
    for record in records or []:
        if isinstance(record, dict):
            result.append(float(record.get("sec", 0)))
        else:
            result.append(float(record))
    return result


def _fmt(sec: float) -> str:
    if sec < 10:
        return f"{sec:.1f}s"
    if sec < 60:
        return f"{sec:.0f}s"
    minutes, seconds = divmod(sec, 60)
    if minutes < 60:
        return f"{int(minutes)}m {seconds:.0f}s"
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)}h {int(minutes)}m"


def _row(name: str, values: list[float], note: str = "") -> str:
    if not values:
        return f"| {name} | 0 | — | — | — | — | {note} |"
    total = sum(values)
    return (
        f"| {name} | {len(values)} | {_fmt(total / len(values))} | {_fmt(total)} | "
        f"{_fmt(min(values))} | {_fmt(max(values))} | {note} |"
    )


# ─── 报告组装 ──────────────────────────────────────────
def build_op_report(data: dict, full_date: str, source_log: str) -> str:
    ops = data.get("operations", {})
    events = data.get("event_counts", {}) or {}
    total_clock_sec = data.get("total_elapsed_sec") or 0
    date_iso = f"{full_date[:4]}-{full_date[4:6]}-{full_date[6:]}"

    # 日志来源
    groq_secs = _secs(ops.get("transcribe_groq", []))
    bailian_secs = _secs(ops.get("transcribe_bailian", []))
    mlx_secs = _secs(ops.get("transcribe_mlx", []))
    audio_secs = _secs(ops.get("extract_audio", []))
    summary_done = int(events.get("summary_glm_done", 0))
    summary_skip = int(events.get("summary_glm_skip", 0))
    bailian_calls = int(events.get("bailian_calls", 0))
    bailian_polls = int(events.get("bailian_polls", 0))
    groq_success_log = int(events.get("groq_success", 0))
    mlx_completes_log = int(events.get("mlx_completes", 0))
    groq_429 = int(events.get("groq_429_lines", 0))

    # vault 事后分类
    vault = _scan_vault(date_iso)

    now = datetime.now(TZ).isoformat(timespec="seconds")
    measurable_total = sum(audio_secs) + sum(groq_secs) + sum(bailian_secs) + sum(mlx_secs)

    lines: list[str] = []
    lines += [
        f"# crawl OP 报告 {date_iso}",
        "",
        f"> 生成时间: {now}",
        f"> 跑批日志: `{source_log}`",
        f"> 墙钟总耗时: {_fmt(total_clock_sec)}（来自日志最后 [N/7] 进度行总计）",
        "> 口径: 每张表只统计一个 OP 环节, 不跨环节相加。",
        "",
        "## 总览",
        "",
        "| 指标 | 数值 |",
        "|---|---:|",
        f"| vault 入库总篇数 | {vault['total_published']} |",
        f"| 视频帖 | {vault['video_total']}（ASR 成功 **{vault['video_with_transcript']}**, ASR 失败 **{vault['video_asr_failed']}**）|",
        f"| 纯图文帖 | {vault['image_total']} |",
        "",
        "## OP-1 fetch（抓取）",
        "",
        "| 平台 | 当日入库篇数 |",
        "|---|---:|",
    ]
    for plat, count in sorted(vault["by_platform"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {plat} | {count} |")
    if not vault["by_platform"]:
        lines.append("| (无) | 0 |")
    lines += [
        "",
        "> 数据来源: vault 当日 `YYYY-MM-DD_*.md` 实际文件计数.",
        "> 备注: 入库数 = watchlist/clip 当日全部成功 publish 的笔记.",
        "",
        "## OP-2 classify（内容分类与 ASR 标记）",
        "",
        "| 分类 | 篇数 | 说明 |",
        "|---|---:|---|",
        f"| video_with_transcript | {vault['video_with_transcript']} | 视频 + ASR 成功（含 `## 转录 (...)` 段）|",
        f"| **video_asr_failed** | **{vault['video_asr_failed']}** | **视频但 ASR 失败(只有标题)** ← 关键诊断信号 |",
        f"| image_post | {vault['image_total']} | 纯图文帖子（无需 ASR）|",
        "",
        "> 判别依据:`source_url` 含 `/video/` 即视频帖; body 含 `## 转录` 段即 ASR 成功.",
        "> `video_asr_failed` 通常由 ASR 链 (groq→bailian→mlx) 全失败导致, 可在下次跑批触发重试.",
        "",
    ]
    if vault["video_failed_paths"]:
        lines += [
            "### ASR 失败清单（可作为下次重试依据）",
            "",
        ]
        for p in vault["video_failed_paths"][:30]:
            lines.append(f"- `{p}`")
        if len(vault["video_failed_paths"]) > 30:
            lines.append(f"- ... 还有 {len(vault['video_failed_paths']) - 30} 篇")
        lines.append("")

    lines += [
        "## OP-3 download（音频抽取）",
        "",
        "| OP | 次数 | 平均 | 总耗时 | 最短 | 最长 | 说明 |",
        "|---|---:|---:|---:|---:|---:|---|",
        _row("extract_audio", audio_secs, "ffmpeg 从视频 URL 流式抽 WAV"),
        "",
        "> 数据来源: 日志结构化行 `[audio] 抽取完成 ... 总=Xs`",
        "",
        "## OP-4 transcribe（ASR 转写）",
        "",
        "| provider | 日志调用次数 | 日志成功次数 | 平均/总耗时 | 备注 |",
        "|---|---:|---:|---|---|",
        f"| groq | {groq_success_log + groq_429} | {groq_success_log} | {_fmt(sum(groq_secs))} / avg {_fmt(sum(groq_secs) / len(groq_secs)) if groq_secs else 0} | 429 触发 {groq_429} 次 |"
        if groq_secs or groq_success_log else
        "| groq | 0 | 0 | — | 429 触发 0 次 |",
        f"| bailian | {bailian_calls} (submit) / {bailian_polls} (poll SUCCEEDED) | {bailian_polls} | {_fmt(sum(bailian_secs))} / avg {_fmt(sum(bailian_secs) / len(bailian_secs)) if bailian_secs else 0} | 异步轮询模式 |"
        if bailian_secs or bailian_calls else
        "| bailian | 0 | 0 | — | 异步轮询模式 |",
        f"| mlx | {mlx_completes_log} | {mlx_completes_log} | {_fmt(sum(mlx_secs))} / avg {_fmt(sum(mlx_secs) / len(mlx_secs)) if mlx_secs else 0} | 本地 ANE 兜底 |"
        if mlx_secs or mlx_completes_log else
        "| mlx | 0 | 0 | — | 本地 ANE 兜底 |",
        "",
        "> 关键诊断: vault `video_asr_failed` 与日志失败次数差额 = 需要查 transcribe 异常路径.",
        "> 注意: 日志成功次数 + 日志失败次数 ≠ vault ASR 成功篇数（vault 是唯一真实值）。",
        "",
        "## OP-5 summarize（内容总结 GLM）",
        "",
        "| 事件 | 次数 | 说明 |",
        "|---|---:|---|",
        f"| summary_glm_done | {summary_done} | 总结完成（去重后唯一总结数）|",
        f"| summary_glm_skip | {summary_skip} | 跳过总结（已有或无正文）|",
        "",
        "> 数据来源: 日志 `📝 总结完成` / `⚠️ 总结跳过` 事件行",
        "> 备注: 日志只记录完成/跳过事件, 未记录 LLM 耗时, 故不展示 mean/total.",
        "",
        "---",
        f"> 当前可计量 OP 总耗时: **{_fmt(measurable_total)}**（download + transcribe 累计, 不代表墙钟）",
        f"> vault 真实入库 = {vault['total_published']} 篇, 视频转录失败 = {vault['video_asr_failed']} 篇",
    ]
    return "\n".join(lines) + "\n"


def build_md(data: dict, *_args, **_kwargs) -> str:
    """兼容旧内部调用。"""
    full_date = str(data.get("_report_date") or datetime.now(TZ).strftime("%Y%m%d"))
    source_log = str(data.get("_source_log") or "unknown")
    return build_op_report(data, full_date, source_log)


def _resolve_data() -> tuple[dict, str]:
    """v2: 优先读 run_tag 的 events.jsonl, 失败 fallback 到 _parse_latest_run(log).

    Returns:
        (data_dict, source_label)
    """
    try:
        tag = _find_latest_run_tag()
        if tag:
            data = _parse_run_tag(tag)
            data["_source"] = f"run_tag:{tag}"
            return data, f"events.jsonl ({tag})"
    except Exception as e:
        print(f"  [report] _parse_run_tag 失败: {e}", flush=True)
    # fallback: parse log
    try:
        log_path = _find_log(_normalize_date(None)[0], _normalize_date(None)[1])
        data = _parse_latest_run(log_path)
        data["_source"] = f"log:{log_path.name}"
        return data, f"log ({log_path.name})"
    except Exception as e:
        raise RuntimeError(f"v1 log 解析也失败: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(description="生成最后一次跑批的 OP 报告")
    parser.add_argument("--date", "-d", default=None, help="MMDD 或 YYYYMMDD")
    parser.add_argument("--log", default=None, help="显式指定日志文件")
    args = parser.parse_args()

    full_date, mmdd, _ = _normalize_date(args.date)
    log_path = Path(args.log).expanduser() if args.log else _find_log(full_date, mmdd)
    data = _parse_latest_run(log_path)
    md = build_op_report(data, full_date, log_path.name)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    output = REPORT_DIR / f"crawl_op_{full_date}.md"
    output.write_text(md, encoding="utf-8")
    print(md, end="")
    print(f"[report_timing] ok: {output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
