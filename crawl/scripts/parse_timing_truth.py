#!/usr/bin/env python3
"""
parse_timing_truth.py — 从 supervisor 跑批日志中**完整**、**真实**地
提取所有可观察 op 的耗时与次数。

⚠️  取代 cron-run report_timing.py / common-report skill 那种"以已发笔记反推"
   的凑数法。直接 grep 日志原文，不做任何推断。
"""
import re
import sys
import json
from collections import defaultdict, OrderedDict
from pathlib import Path


def parse_log(path: str, date_filter: str = None, latest_run: bool = False) -> dict:
    """解析日志文件。
    
    Args:
        path: 日志文件路径
        date_filter: 可选，格式 YYYYMMDD，只解析该日期的行（用于多天日志混在一起时）。
        latest_run: 只解析最后一个完整跑批入口到文件末尾，避免追加日志混入旧批次。
    """
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    all_lines = text.splitlines()

    # OP 报告默认使用最后一次跑批，避免同一个 launchd 日志追加多轮后重复计数。
    if latest_run:
        starts = [
            i for i, line in enumerate(all_lines)
            if "📦 ominicrawl all 流程 - 日期:" in line
        ]
        lines = all_lines[starts[-1]:] if starts else all_lines
    # 如果指定了日期过滤，只取该日期的行（跳过其他日期的历史数据）
    elif date_filter:
        # 寻找 "📦 ominicrawl all 流程 - 日期: YYYYMMDD" 后的行
        today_start = None
        for i, line in enumerate(all_lines):
            if f"omnicrawl all 流程 - 日期: {date_filter}" in line:
                today_start = i
                break
        if today_start is not None:
            # 找到下一个 run 入口就停止
            lines = []
            for line in all_lines[today_start:]:
                if lines and "omnicrawl 统一入口: all" in line and date_filter not in line:
                    break
                lines.append(line)
        else:
            # 没找到精确匹配，用时间戳过滤（行首 HH:MM:SS 格式）
            lines = [l for l in all_lines if l[:2].isdigit() and int(l[:2]) >= 0]
            print(f"[parse_timing] 警告: 未找到 'omnicrawl 统一入口: all {date_filter}'，解析全部 {len(lines)} 行", file=sys.stderr)
    else:
        lines = all_lines
    details = OrderedDict()  # op_name -> list[{sec, context}]
    ops = OrderedDict()  # op_name -> list[float]

    # ── 进度行: [N/7] xxx 0/Y (0%) | 本阶段 20s | 总计 20s
    progress_re = re.compile(
        r"\[(\d)/7\]\s+(?:进入平台：\s*)?(.+?)\s*(\d+/\d+)\s*(?:\(\d+%\)\s*)?\s*\|\s*本阶段\s*(\d+)([smh])\s*\|\s*总计\s*(.+)"
    )
    platform_progress = []

    # ── [audio] 抽取完成 / 抽取失败
    audio_re = re.compile(
        r"\[audio\]\s+(?:抽取完成|抽取失败)\s+(?:size=[\d.]+MB\s+)?下载=([\d.]+)s\s+转码=([\d.]+)s\s+总=([\d.]+)s"
    )

    # ── [bailian] SUCCEEDED poll #N (Xs)
    bailian_poll_re = re.compile(r"\[bailian\]\s+poll\s+#(\d+)\s+\(([\d.]+)s\)\s+SUCCEEDED")

    # ── [groq] 成功 (\d+) chars (sec)
    groq_success_re = re.compile(r"\[groq\]\s+.*?(?:成功|完成).*?(\d+\.?\d*)s", re.I)

    # ── [mlx] ... 推理 (X.Xs)
    # ── [mlx-async] ... (X.Xs)
    mlx_re = re.compile(r"\[mlx(?:-async)?\]\s+.*?(\d+\.\d+)s")

    # ── [opencli] ... 可能耗时长
    opencli_start_re = re.compile(r"\[opencli\s+回退\]\s+(?:浏览器渲染|开始)\s*:?\s*(.+)$")
    opencli_end_markers = [
        re.compile(r"\[opencli\]\s+sync\s+完成"),
        re.compile(r"\[opencli\]\s+daemon\s+stop\s+完成"),
        re.compile(r"\[opencli\]\s+已关闭独立 Chrome"),
        re.compile(r"\[opencli\]\s+检测到已连 Chrome"),
        re.compile(r"\[opencli\]\s+已拉起副 profile Chrome"),
    ]

    # ── skip_dedup → dedup: xxx 已缓存 / 已存于
    dedup_re = re.compile(r"\[dedup[ _]vault\]|\ud83d\udeab|\u23ed\ufe0f\s*dedup|⏭\s*dedup|\ud83d\udeab\s*正文过少")

    # ── publish_vault → 💾 subscription/...
    publish_re = re.compile(r"\ud83d\udcbe subscription/(.+)")

    # ── summarize_glm 完
    summary_done_re = re.compile(r"\ud83d\udcdd \u603b\u7ed3\u5b8c\u6210|⚠️ 总结跳过")

    # ── groq 429 计数
    groq_429_re = re.compile(r"\[groq\].*?(?:429|限流)")

    # ── 平台进入 + 平台结束
    platform_in_re = re.compile(r"\[(\d)/7\]\s+进入平台：\s*(.+)")
    platform_done_re = re.compile(r"(?:✅|OK)\s*(\w+)\s*(?:完成|done)")

    current_platform = None
    last_progress = None
    audio_count = 0
    bailian_count = 0
    bailian_secs = []
    publish_count = 0

    raw_counts = defaultdict(int)
    opencli_blocks = []
    in_opencli = False
    opencli_start_line = -1
    last_opencli_ctx = None

    for lineno, line in enumerate(lines):
        m = progress_re.search(line)
        if m:
            n, plat, frac, stage_num, stage_unit, total = m.groups()
            platform_progress.append({
                "line": lineno,
                "platform_idx": int(n),
                "platform": plat.strip(),
                "frac": frac,
                "stage_sec": int(stage_num) * (60 if stage_unit == "m" else 3600 if stage_unit == "h" else 1),
                "stage_unit": stage_unit,
                "total": total.strip(),
            })

        m = platform_in_re.search(line)
        if m:
            current_platform = m.group(2).strip()

        m = audio_re.search(line)
        if m:
            dl, tr, total = m.groups()
            audio_count += 1
            raw_counts["audio_extract"] += 1
            # 真实耗时: 总秒数
            ops.setdefault("extract_audio", []).append(float(total))
            details.setdefault("extract_audio", []).append({
                "sec": float(total),
                "download_s": float(dl),
                "transcode_s": float(tr),
                "platform": current_platform,
            })

        m = bailian_poll_re.search(line)
        if m:
            n, s = m.groups()
            raw_counts["bailian_polls"] += 1
            # 仅在 SUCCEEDED poll 上记 transcribe 总耗时
            cur = float(s)
            bailian_secs.append(cur)
            ops.setdefault("transcribe_bailian", []).append(cur)

        if "[bailian] task_id=" in line:
            bailian_count += 1
            raw_counts["bailian_calls"] += 1

        m = groq_success_re.search(line)
        if m:
            ops.setdefault("transcribe_groq", []).append(float(m.group(1)))
            raw_counts["groq_success"] += 1

        m = mlx_re.search(line)
        if m:
            ops.setdefault("transcribe_mlx", []).append(float(m.group(1)))
            raw_counts["mlx_completes"] += 1

        if groq_429_re.search(line):
            raw_counts["groq_429_lines"] += 1

        # 2026-07-30: 腾讯云 ASR 事件统计
        if "[tencent_asr] 成功" in line:
            raw_counts["tencent_asr_success"] = raw_counts.get("tencent_asr_success", 0) + 1

        if "📝 总结完成" in line:
            # 历史日志没有总结耗时，只能记录完成事件；绝不伪造 1 秒耗时。
            raw_counts["summary_glm_done"] += 1
        elif "⚠️ 总结跳过" in line:
            raw_counts["summary_glm_skip"] += 1

        m = opencli_start_re.search(line)
        if m:
            in_opencli = True
            opencli_start_line = lineno
            last_opencli_ctx = m.group(1).strip()

        for em in opencli_end_markers:
            if em.search(line) and in_opencli:
                # 用上次进度行 + 下次进度行反推
                # 简化: 记为"段耗时"=下一行 supervisor 进度差
                in_opencli = False
                start_line = opencli_start_line
                opencli_blocks.append({
                    "start": start_line,
                    "end": lineno,
                    "ctx": last_opencli_ctx,
                })
                break

        if "skip_dedup" in line or "已缓存" in line or "已存于" in line:
            raw_counts["dedup_lines"] += 1

        if publish_re.search(line):
            raw_counts["publish_lines"] += 1
            publish_count += 1

        if "Watchlist 全流程完成" in line or "[Supervisor] 全流程结束" in line:
            raw_counts["supervisor_end"] += 1

    # ── 把 progress 行的"本阶段 / 总计"差分作为 fetch 真实耗时
    # 同一平台在最后阶段 diff = 该平台总耗时
    per_platform = OrderedDict()
    last_p = None
    for p in platform_progress:
        cur = p["platform"]
        if cur not in per_platform:
            per_platform[cur] = {"first_total": p["total"], "last_total": p["total"], "stage_max": p["stage_sec"]}
        else:
            per_platform[cur]["last_total"] = p["total"]
            per_platform[cur]["stage_max"] = max(per_platform[cur]["stage_max"], p["stage_sec"])

    # ── 全流程开始结束时间
    started_at = None
    for line in lines[:50]:
        if "Watchlist 模式" in line:
            m2 = re.search(r"date=(\d{8})", line)
            if m2:
                started_at = m2.group(1)
            break

    finished_at = None
    for line in lines[-100:]:
        if "全流程结束" in line:
            finished_at = line

    # ── 把 supervisor 自报 [N/7] 行的"总计 Xm Xs"解析为总墙钟
    total_clock_sec = None
    last = platform_progress[-1] if platform_progress else None
    if last:
        mtotal = re.match(r"(\d+)m\s*(\d+)s", last["total"]) or re.match(r"(\d+)s", last["total"])
        if mtotal:
            if len(mtotal.groups()) == 2:
                total_clock_sec = int(mtotal.group(1)) * 60 + int(mtotal.group(2))
            else:
                total_clock_sec = int(mtotal.group(1))

    # ── 汇总
    summary = {
        "started_at": started_at,
        "finished_marker": finished_at,
        "total_clock_sec": total_clock_sec,
        "raw_counts": dict(raw_counts),
        "platform_progress_count": len(platform_progress),
        "platform_progress": platform_progress,
        "per_platform_stage_max_sec": {k: v["stage_max"] for k, v in per_platform.items()},
    }

    return {
        "ops": dict(ops),
        "details": dict(details),
        "summary": summary,
        "raw_counts": dict(raw_counts),
    }


def fmt_ops(ops: dict) -> str:
    rows = []
    rows.append(f"{'op':<25} {'count':>5} {'avg':>8} {'total':>9} {'min':>7} {'max':>7}")
    rows.append("-" * 70)
    sorted_ops = sorted(ops.items(), key=lambda kv: (-len(kv[1]) if kv[1] else 0, kv[0]))
    # 重新按 count 降序
    sorted_ops = sorted(ops.items(), key=lambda kv: -len(kv[1]))
    for name, secs in sorted_ops:
        if not secs:
            continue
        total = sum(secs)
        avg = total / len(secs)
        rows.append(f"{name:<25} {len(secs):>5} {avg:>7.2f}s {total:>8.1f}s {min(secs):>6.2f} {max(secs):>6.2f}")
    return "\n".join(rows)


def errors_from_log(log_path: str) -> list:
    """从日志中提取错误行，转换为 report_timing.py 所需格式。"""
    errors = []
    try:
        text = Path(log_path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return errors
    # 2026-07-30: 统一错误格式 "[HH:MM:SS+08:00] [SEV] op: msg"
    err_re = re.compile(r"\[(\d{2}:\d{2}:\d{2}\+\d{2}:\d{2})\]\s+\[(\w+)\]\s+(\w+):\s*(.+)")
    for line in text.splitlines():
        m = err_re.search(line)
        if m:
            errors.append({
                "at": m.group(1),
                "severity": m.group(2),
                "op": m.group(3),
                "error": m.group(4).strip()[:200],
            })
    return errors


if __name__ == "__main__":
    log = sys.argv[1] if len(sys.argv) > 1 else "/tmp/watchlist_full.log"
    date_filter = None
    latest_run = "--latest-run" in sys.argv
    for i, arg in enumerate(sys.argv):
        if arg == "--date" and i+1 < len(sys.argv):
            date_filter = sys.argv[i+1]
            break
    data = parse_log(log, date_filter=date_filter, latest_run=latest_run)

    # ── 转换为 report_timing.py 所需格式 ────────────────────────────────
    import json
    # ops: {op_name: [sec, ...]} → {op_name: [{sec: X, meta: {}}, ...]}
    ops_formatted = {}
    for op_name, secs in data["ops"].items():
        if not secs:
            continue
        # 尝试从 details 拿 metadata
        details = data.get("details", {}).get(op_name, [])
        if details and len(details) == len(secs):
            ops_formatted[op_name] = [{"sec": s, "meta": d.get("meta", {})} for s, d in zip(secs, details)]
        else:
            ops_formatted[op_name] = [{"sec": s, "meta": {}} for s in secs]

    timing_output = {
        "run_started_at": data.get("summary", {}).get("started_at", ""),
        "run_finished_at": "",
        "total_elapsed_sec": data.get("summary", {}).get("total_clock_sec", 0),
        "total_items": max(
            len(data["ops"].get("transcribe_bailian", [])),
            len(data["ops"].get("transcribe_groq", [])),
            len(data["ops"].get("transcribe_mlx", [])),
            data.get("raw_counts", {}).get("summary_glm_done", 0),
        ),
        "operations": ops_formatted,
        "event_counts": data.get("raw_counts", {}),
        "provider_switches": [],
        "errors": errors_from_log(log),
    }

    # 输出两份: JSON (truth.json) + 人类可读报告 (stderr)
    json_out = json.dumps(timing_output, ensure_ascii=False, indent=2)
    print(json_out)  # stdout → 被 tee 到 truth.json

    print(file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    print(f"日志: {log}", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    print(file=sys.stderr)
    print("## 一、按 op 实测（来自日志原文结构化解析）", file=sys.stderr)
    print(file=sys.stderr)
    print(fmt_ops(data["ops"]), file=sys.stderr)
    print(file=sys.stderr)
    print("## 二、原始计数（所有可观察的事件行数）", file=sys.stderr)
    print(file=sys.stderr)
    for k, v in sorted(data["raw_counts"].items()):
        print(f"  {k:<30} {v:>4}", file=sys.stderr)
    print(file=sys.stderr)
    print("## 三、平台进度节点", file=sys.stderr)
    print(file=sys.stderr)
    print(f"  总墙钟: {data['summary']['total_clock_sec']}s ({data['summary']['total_clock_sec']/60:.1f}min)" if data['summary']['total_clock_sec'] else "  未抓到", file=sys.stderr)
    print(f"  started_at: {data['summary']['started_at']}", file=sys.stderr)
    print(file=sys.stderr)
    print("## 四、extract_audio 详细", file=sys.stderr)
    print(file=sys.stderr)
    if "extract_audio" in data["details"]:
        for i, d in enumerate(data["details"]["extract_audio"], 1):
            print(f"  #{i:>2} 下载={d['download_s']:.2f}s  转码={d['transcode_s']:.2f}s  总={d['sec']:.2f}s", file=sys.stderr)
    else:
        print("  (无)", file=sys.stderr)
    print(file=sys.stderr)
    print("## 五、错误记录", file=sys.stderr)
    print(file=sys.stderr)
    for e in timing_output["errors"][:10]:
        print(f"  [{e['at']}] [{e['severity']}] {e['op']}: {e['error'][:100]}", file=sys.stderr)
    if not timing_output["errors"]:
        print("  (无)", file=sys.stderr)
