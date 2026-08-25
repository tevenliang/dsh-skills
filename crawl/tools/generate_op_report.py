#!/usr/bin/env python3
"""generate_op_report.py — 自动生成 crawl 跑批报告 (2026-08-03 v2).

设计 (修 #19 升级):
- supervisor.cmd_all() 跑完后自动调, 不需手动触发
- 数据源 (按 sample_0726 范本):
  1. crawl/state/supervisor.json (status/exit_code/last_heartbeat)
  2. logs/launchd_supervisor_<DATE>.out (平台切换, Groq 429 详情, ASR.FATAL, retry)
  3. vault/subscription/<plat>/*.md mtime 在跑批窗口内 (vault 入库, 唯一真实值)
  4. parse_timing_truth.py 输出 (各 op 耗时)
- 输出: vault/04_agent/report/crawl_op_<DATE>.md (sample_0726 风格)

用法:
  python3 generate_op_report.py --date 20260803                    # 找当天最新 log
  python3 generate_op_report.py --date 20260803 --log-path PATH    # 指定 log
  python3 generate_op_report.py --date 20260803 --no-write         # 只打 stdout
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


CRAWL_ROOT = Path(os.path.expanduser("~/.agents/skills/crawl"))
VAULT_DEFAULT = Path(os.path.expanduser("~/Documents/steven_vault"))
OUT_DIR = VAULT_DEFAULT / "04_agent" / "report"


# ════════════════════════════════════════════════════════
# Log 查找 + 基础 parse
# ════════════════════════════════════════════════════════

def find_log(skill_root: Path, date: str) -> Path:
    """按日期找最新日志; 找不到 fallback 到最新 log."""
    log_dir = skill_root / "logs"
    # 1. 优先 launchd_supervisor_<DATE>.out
    launchd = sorted(log_dir.glob(f"launchd_supervisor_{date}.out"), reverse=True)
    if launchd:
        return launchd[0]
    # 2. 再 run_<DATE>_*.out
    candidates = sorted(log_dir.glob(f"run_{date}_*.out"), reverse=True)
    if candidates:
        return candidates[0]
    # 3. fallback 最新
    return sorted(log_dir.glob("*.out"), reverse=True)[0] if log_dir.glob("*.out") else Path("/tmp/watchlist_full.log")


def parse_truth(skill_root: Path, log_path: Path, py: str = sys.executable) -> dict:
    """调 scripts/parse_timing_truth.py 解析日志, 返回 truth dict."""
    parse_script = skill_root / "scripts" / "parse_timing_truth.py"
    if not parse_script.exists():
        return {}
    try:
        r = subprocess.run(
            [py, str(parse_script), str(log_path), "--latest-run"],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            return {}
        json_start = r.stdout.find("{")
        if json_start < 0:
            return {}
        return json.loads(r.stdout[json_start:])
    except Exception:
        return {}


def parse_log_extras(log_path: Path) -> dict:
    """从 launchd log 提取 parse_timing_truth 没结构化的字段 (sample_0726 维度)."""
    extras = {
        "supervisor_pid": None,
        "run_tag": None,
        "start_iso": None,
        "total_elapsed_text": None,
        "exit_code": None,
        "platforms": [],          # [{name, elapsed_at_enter}]
        "platform_new_counts": {}, # 平台日志最后一次“本阶段新增 N 篇”
        "groq_429_records": [],   # [{at, limit, used, requested, retry_after}]
        "asr_fatal_records": [],  # [{bvid, reason}]
        "groq_success_chars": [], # [int]
        "groq_timing_records": [], # [{chars, elapsed_s}]，仅新日志可得
        "wav_to_mp3_records": [], # [(wav_mb, mp3_kb)]
        "dedup_count": 0,
        "extract_audio_records": [],  # [(download_s, transcode_s, total_s)]
        "summary_done_count": 0,
        "summary_skip_count": 0,
        "handoff_vm_count": 0,    # 本次 run handoff 到 VM 的视频数 (3.1.0 ASR 唯一路径)
    }

    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return extras

    for line in text.splitlines():
        # Supervisor 启动 + run_tag + 总耗时
        m = re.search(r"\[Supervisor\]\s+启动\s+PID=(\d+)\s+run_tag=(\S+)", line)
        if m and extras["supervisor_pid"] is None:
            extras["supervisor_pid"] = m.group(1)
            extras["run_tag"] = m.group(2)

        m = re.search(r"\[Supervisor\]\s+全流程结束[^\\n]\n]*?退出码:\s*(\d+)\s+总耗时:\s*(\S+)", line)
        if m:
            extras["exit_code"] = int(m.group(1))
            extras["total_elapsed_text"] = m.group(2)

        # 进入平台
        m = re.search(r"\[(\d+)/(\d+)\]\s+进入平台[:：]\s*(\S+)\s*\(已用时\s*(\S+)\)", line)
        if m:
            extras["platforms"].append({
                "idx": int(m.group(1)),
                "total": int(m.group(2)),
                "name": m.group(3).strip(),
                "elapsed_at_enter": m.group(4),
            })

        # 平台本批新增数：取该平台日志中最后一次累计值，避免用 vault 历史文件数冒充本批产出。
        m = re.search(r"📊\s*\[([^]]+)\]\s*本阶段(?:新增\s*(\d+)|\s*(\d+)\s*新增)", line)
        if m:
            extras["platform_new_counts"][m.group(1).strip()] = int(m.group(2) or m.group(3))

        # 某些图文平台不打印“本阶段新增”，只打印“平台完成: N 个文件”。
        m = re.search(r"✅\s*(京东|贴吧|小红书|Boss直聘)完成[:：]\s*(\d+)\s*个文件", line)
        if m:
            done_map = {"京东": "jd", "贴吧": "tieba", "小红书": "xiaohongshu", "Boss直聘": "boss"}
            extras["platform_new_counts"][done_map[m.group(1)]] = int(m.group(2))

        # Groq 429 触发
        m = re.search(
            r"\[groq\]\s+额度限流 \(HTTP 429\)[^\n]*?Limit\s+(\d+),\s+Used\s+(\d+),\s+Requested\s+(\d+)[^\n]*?retry-after:\s*(\d+)",
            line,
        )
        if m:
            extras["groq_429_records"].append({
                "limit": int(m.group(1)),
                "used": int(m.group(2)),
                "requested": int(m.group(3)),
                "retry_after_s": int(m.group(4)),
            })

        # ASR.FATAL
        m = re.search(r"\[ASR\.FATAL\][^()]*\(([^)]+)\):\s*([^—\n]+?)(?:\s*—\s*(.+))?$", line)
        if m:
            extras["asr_fatal_records"].append({
                "key": m.group(1).strip(),  # bvid=BVxxx or similar
                "reason": m.group(2).strip(),
                "detail": m.group(3).strip() if m.group(3) else "",
            })

        # Groq 转录成功 chars
        m = re.search(r"\[(?:groq|groq_429)\]\s+成功\s+(\d+)\s+chars(?:\s+\(([\d.]+)s\))?", line)
        if m:
            chars = int(m.group(1))
            extras["groq_success_chars"].append(chars)
            # 旧日志没有逐条耗时；不要用音频抽取时间或字符数臆测。
            if m.group(2) is not None:
                extras["groq_timing_records"].append({"chars": chars, "elapsed_s": float(m.group(2))})

        # wav → mp3 压缩记录
        m = re.search(r"\[groq\]\s+wav\s+([\d.]+)MB\s+->\s+mp3\s+(\d+)KB\s+\(压缩\s+(\d+)x\)", line)
        if m:
            extras["wav_to_mp3_records"].append({
                "wav_mb": float(m.group(1)),
                "mp3_kb": int(m.group(2)),
                "ratio": int(m.group(3)),
            })

        # audio 抽取完成
        m = re.search(r"\[audio\]\s+抽取完成\s+size=[\d.]+MB\s+下载=([\d.]+)s\s+转码=([\d.]+)s\s+总=([\d.]+)s", line)
        if m:
            extras["extract_audio_records"].append({
                "download_s": float(m.group(1)),
                "transcode_s": float(m.group(2)),
                "total_s": float(m.group(3)),
            })

        # dedup
        if re.search(r"⏭️\s+(已缓存|已存于|dedup)", line):
            extras["dedup_count"] += 1

        # VM handoff 计数 (3.1.0 ASR 唯一路径: 本地上传音频到 VM inbox)
        if "已上传 VM inbox" in line:
            extras["handoff_vm_count"] += 1

        # summary
        if "📝 总结完成" in line:
            extras["summary_done_count"] += 1
        if "⚠️ 总结跳过" in line:
            extras["summary_skip_count"] += 1

    return extras


def parse_supervisor_json(skill_root: Path) -> dict:
    """读 state/supervisor.json 拿 status/exit_code/last_heartbeat."""
    p = skill_root / "state" / "supervisor.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def parse_elapsed_to_sec(text: str) -> float:
    """把 '35min' / '120s' / '1h5min' 转成秒."""
    if not text:
        return 0.0
    text = text.strip()
    total = 0.0
    m = re.match(r"(\d+)h", text)
    if m:
        total += int(m.group(1)) * 3600
        text = text[m.end():]
    m = re.match(r"(\d+)min", text)
    if m:
        total += int(m.group(1)) * 60
        text = text[m.end():]
    m = re.match(r"([\d.]+)s", text)
    if m:
        total += float(m.group(1))
    return total


# ════════════════════════════════════════════════════════
# Vault 扫描
# ════════════════════════════════════════════════════════

PLATFORMS = ["douyin", "bilibili", "xiaohongshu", "boss", "jd", "linkedin", "tieba", "wechat"]


def scan_vault_for_window(vault_root: Path, start_iso: str, window_sec: float = 4 * 3600,
                          report_date: str = "") -> dict:
    """扫 vault/subscription/<plat>/, 找出本次跑批入库的 md.

    判定策略 (二选一即算):
    A) 文件名以 "<YYYY-MM-DD>_" 开头 (report_date, 如 2026-08-03)
    B) mtime 在 [start, start+window] 范围内

    返回 {plat: {total, has_transcript, files}}
    """
    # 解析 start_ts
    start_ts = 0
    if start_iso:
        try:
            start_ts = datetime.fromisoformat(start_iso).timestamp()
        except Exception:
            start_ts = 0
    end_ts = start_ts + window_sec if start_ts else 0

    # 文件名前缀 (e.g. 2026-08-03_)
    name_prefix = f"{report_date}-" if report_date and len(report_date) == 8 else ""
    if report_date and len(report_date) == 8:
        name_prefix = f"{report_date[:4]}-{report_date[4:6]}-{report_date[6:]}_"

    results = {}
    sub_root = vault_root / "subscription"
    if not sub_root.is_dir():
        return results

    for plat_dir in sorted(sub_root.iterdir()):
        if not plat_dir.is_dir():
            continue
        plat_name = plat_dir.name
        plat_rec = {"total": 0, "has_transcript": 0, "files": []}
        for md in plat_dir.rglob("*.md"):
            if md.name.startswith(".") or md.name == "index.md":
                continue
            try:
                mt = md.stat().st_mtime
            except Exception:
                continue
            # 二选一
            in_window = start_ts and (start_ts <= mt <= end_ts)
            name_match = name_prefix and md.name.startswith(name_prefix)
            if not (in_window or name_match):
                continue
            plat_rec["total"] += 1
            plat_rec["files"].append(md)
            try:
                txt = md.read_text()
            except Exception:
                continue
            tm = re.search(r"##\s*转录\s*\n+(.*?)(?=\n##|\Z)", txt, re.DOTALL)
            if tm and len(tm.group(1).strip()) > 100:
                plat_rec["has_transcript"] += 1
        results[plat_name] = plat_rec
    return results


def detect_run_window(log_path: Path) -> tuple:
    """从 log 推断跑批起始/结束时间.

    策略:
    1. 解析 "run_tag=run_YYYYMMDD_HHMMSS_PID" → start_iso
    2. 读到 "[Supervisor] 全流程结束" 后, 下一行 "退出码: 0" + 再下一行 "总耗时: 35min"
    3. 多 run 时取最后一个时长 >= 30s 的真实 run (跳过 5s recovery run)

    返回 (start_iso, end_iso, total_sec). 拿不到就 (None, None, 0).
    """
    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None, None, 0.0

    lines = text.splitlines()
    runs = []  # [{start_dt, duration_s}]
    cur_start = None
    for i, line in enumerate(lines):
        m = re.search(r"\[Supervisor\]\s+启动\s+PID=\d+\s+run_tag=run_(\d{8})_(\d{6})_\d+", line)
        if m:
            try:
                cur_start = datetime.strptime(f"{m.group(1)}_{m.group(2)}", "%Y%m%d_%H%M%S")
            except Exception:
                cur_start = None
            continue
        if "[Supervisor] 全流程结束" in line:
            # 找接下来 3 行内的 总耗时: ...
            duration_s = 0.0
            for j in range(i + 1, min(i + 5, len(lines))):
                dm = re.search(r"总耗时[:：]\s*(\S+)", lines[j])
                if dm:
                    duration_s = parse_elapsed_to_sec(dm.group(1))
                    break
            if cur_start is not None:
                runs.append({"start_dt": cur_start, "duration_s": duration_s})
            cur_start = None

    real = [r for r in runs if r["duration_s"] >= 30]
    if not real:
        real = runs
    if not real:
        return None, None, 0.0
    last = real[-1]
    start_dt = last["start_dt"]
    total_sec = last["duration_s"]
    end_dt = datetime.fromtimestamp(start_dt.timestamp() + total_sec)
    return start_dt.isoformat(), end_dt.isoformat(), total_sec


def event_run_window(skill_root: Path, run_tag: str):
    """从指定 run 的事件流计算整批墙钟，不读取全局 supervisor.json。"""
    path = skill_root / "state" / f"{run_tag}.events.jsonl"
    if not path.exists():
        return None, None, 0.0
    events = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try: events.append(json.loads(line))
        except Exception: pass
    started = next((e for e in events if e.get("event") == "run_started"), None)
    finished = next((e for e in reversed(events) if e.get("event") == "run_finished"), None)
    if started and finished:
        a = datetime.fromisoformat(started["ts"]); b = datetime.fromisoformat(finished["ts"])
        return a.isoformat(), b.isoformat(), (b-a).total_seconds()
    # 兼容 0804 旧批：用同一事件流的子进程首尾事件，避免 supervisor.json 局部耗时
    ts = [datetime.fromisoformat(e["ts"]) for e in events if e.get("ts")]
    if len(ts) >= 2:
        a, b = min(ts), max(ts)
        return a.isoformat(), b.isoformat(), (b-a).total_seconds()
    return None, None, 0.0


def parse_vm_report(vault_root: Path, date: str) -> dict:
    """读 VM 端转录回执 crawl_op_vm_<date>.md, 提取转录耗时/篇数/处理窗口.

    3.1.0 起 ASR 唯一路径改为 VM, 转录是本地 handoff 之后的异步阶段,
    耗时记录在 VM 端回执里, 不在本地墙钟内. 本函数供本地 OP 报告合并展示.

    返回 dict:
      exists, total, success, fail,
      by_platform: {plat: {success, fail, cum_sec}},
      cum_sec (∑ by_platform.cum_sec), detail_count, first_ts, last_ts, span_sec
    """
    empty = {"exists": False, "total": 0, "success": 0, "fail": 0,
             "by_platform": {}, "cum_sec": 0, "detail_count": 0,
             "first_ts": None, "last_ts": None, "span_sec": 0.0}
    p = vault_root / "04_agent" / "report" / f"crawl_op_vm_{date}.md"
    if not p.exists():
        return dict(empty)
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return dict(empty)

    out = dict(empty)
    out["exists"] = True

    # 基本信息: 本批转录篇数 / 成功 / 失败
    m = re.search(r"本批转录篇数:\s*(\d+)", text)
    if m:
        out["total"] = int(m.group(1))
    m = re.search(r"成功\s*/\s*失败:\s*(\d+)\s*/\s*(\d+)", text)
    if m:
        out["success"] = int(m.group(1))
        out["fail"] = int(m.group(2))

    # 按平台统计表: | bilibili | 48 | 0 | 4496s |
    for pm in re.finditer(r"^\|\s*(\w+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)s\s*\|\s*$", text, re.M):
        plat = pm.group(1).strip()
        if plat == "平台":   # 跳过表头
            continue
        out["by_platform"][plat] = {
            "success": int(pm.group(2)),
            "fail": int(pm.group(3)),
            "cum_sec": int(pm.group(4)),
        }

    # 明细时间戳 (最近 30 条采样) — `2026-08-11 17:38:20` [bilibili] id ✅ 成功 60s
    ts_list = []
    for dm in re.finditer(
        r"`(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})`\s*\[(\w+)\]\s*(\S+)\s*✅\s*成功\s*(\d+)s", text
    ):
        ts_list.append(dm.group(1))
    out["detail_count"] = len(ts_list)
    if ts_list:
        try:
            parsed = [datetime.strptime(t, "%Y-%m-%d %H:%M:%S") for t in ts_list]
            out["first_ts"] = min(parsed).strftime("%Y-%m-%d %H:%M:%S")
            out["last_ts"] = max(parsed).strftime("%Y-%m-%d %H:%M:%S")
            out["span_sec"] = (max(parsed) - min(parsed)).total_seconds()
        except Exception:
            pass

    out["cum_sec"] = sum(v["cum_sec"] for v in out["by_platform"].values())
    if out["total"] == 0 and out["by_platform"]:
        out["total"] = sum(v["success"] for v in out["by_platform"].values())
    return out


# ════════════════════════════════════════════════════════
# Markdown 生成 (sample_0726 风格)
# ════════════════════════════════════════════════════════

def fmt_min(sec: float) -> str:
    return f"{sec/60:.1f}min"


def fmt_pct(part: float, whole: float) -> str:
    if whole <= 0:
        return "—"
    return f"{part/whole*100:.1f}%"


def build_markdown(truth: dict, extras: dict, vault_scan: dict,
                   supervisor_json: dict, report_date: str, log_path: Path,
                   run_window=None, run_tag="", vm=None) -> str:
    """生成 sample_0726 风格的丰富报告."""
    errors = truth.get("errors", [])
    ops = truth.get("operations", {})
    event_counts = truth.get("event_counts", {})

    # 时间元数据
    start_iso, end_iso, total_sec = run_window or detect_run_window(log_path)
    total_min = total_sec / 60 if total_sec > 0 else 0

    # vault 入库统计
    total_vault = sum(r["total"] for r in vault_scan.values())
    total_with_tr = sum(r["has_transcript"] for r in vault_scan.values())
    total_no_tr = total_vault - total_with_tr

    # 转录统计 (legacy Groq, 3.1.0 起已废弃, 仅作兼容显示)
    groq_chars = extras["groq_success_chars"]
    total_chars = sum(groq_chars)
    avg_chars = total_chars / len(groq_chars) if groq_chars else 0
    n_groq_success = len(groq_chars)

    # VM 转录回执 (3.1.0 起 ASR 唯一路径)
    vm = vm or {}
    vm_exists = vm.get("exists", False)
    vm_total = vm.get("total", 0)
    vm_success = vm.get("success", 0)
    vm_fail = vm.get("fail", 0)
    vm_cum_sec = vm.get("cum_sec", 0) or 0
    vm_by_platform = vm.get("by_platform", {})

    # wav→mp3 压缩统计
    wav_mp3 = extras["wav_to_mp3_records"]
    total_wav_mb = sum(r["wav_mb"] for r in wav_mp3)
    total_mp3_kb = sum(r["mp3_kb"] for r in wav_mp3)
    avg_ratio = sum(r["ratio"] for r in wav_mp3) / len(wav_mp3) if wav_mp3 else 0

    # audio extract
    audio_recs = extras["extract_audio_records"]
    audio_total_sec = sum(r["total_s"] for r in audio_recs)

    lines = []
    lines.append(f"# crawl 爬取报告 — {report_date[:4]}-{report_date[4:6]}-{report_date[6:]}")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')} (UTC+8)")
    lines.append(f"> 数据来源: 指定 run 的 events.jsonl（run_tag={run_tag or 'legacy-log'}）；vault 仅用于核对入库结果")
    lines.append(f"> supervisor.json: `status={supervisor_json.get('status', '?')}, exit_code={extras.get('exit_code') or supervisor_json.get('exit_code', '?')}`")
    lines.append("")

    # ── 一、跑批基本信息 ──
    lines.append("## 一、跑批基本信息")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 启动 | {start_iso[:19] if start_iso else '?'} |")
    lines.append(f"| 结束 | {end_iso[:19] if end_iso else '?'} |")
    lines.append(f"| 总墙钟 | {fmt_min(total_sec) if total_sec else extras.get('total_elapsed_text', '?')} |")
    plat_names = [p["name"] for p in extras["platforms"]]
    lines.append(f"| 处理平台 | {len(plat_names)} ({' / '.join(plat_names)}) |")
    logged_output_total = sum(extras.get("platform_new_counts", {}).values())
    handoff_count = extras.get("handoff_vm_count", 0)
    if handoff_count:
        output_cell = f"**{logged_output_total + handoff_count} 篇**（本地落库 {logged_output_total} + handoff VM {handoff_count}）"
    else:
        output_cell = f"**{logged_output_total or total_vault} 篇**（各平台日志“本阶段新增”最终值合计）"
    lines.append(f"| 本批输出 | {output_cell} |")
    lines.append("")

    # ── 二、按平台统计（平台阶段墙钟时间） ──
    lines.append("## 二、按平台统计（墙钟时间）")
    lines.append("")
    lines.append("> 数据来源：跑批结束后解析日志中的“进入平台（已用时）”标记；平台耗时 = 下一平台入口累计时间 − 当前平台入口累计时间，最后平台用总墙钟补齐。")
    lines.append("")
    lines.append("| 平台 | 本批输出 | 平台阶段耗时 | 占总墙钟 | 时间证据 |")
    lines.append("|---|---:|---:|---:|---|")
    # 每个平台耗时 = 下一个平台入口累计时间 - 当前平台入口累计时间。
    # 最后一个平台耗时 = 总墙钟 - 最后平台入口累计时间。
    # 旧实现错误地用“当前入口 - 上一入口”并写到当前平台，导致全表向后错一位。
    platform_total_sec = 0.0
    platform_records = extras.get("platforms", [])
    name_map = {"B站": "bilibili", "抖音": "douyin", "小红书": "xiaohongshu",
                "Boss直聘": "boss", "京东": "jd", "贴吧": "tieba",
                "LinkedIn": "linkedin", "微信": "wechat"}
    platform_rows = []
    for i, p in enumerate(platform_records):
        enter_sec = parse_elapsed_to_sec(p.get("elapsed_at_enter", "0s"))
        if i + 1 < len(platform_records):
            next_sec = parse_elapsed_to_sec(platform_records[i + 1].get("elapsed_at_enter", "0s"))
        else:
            next_sec = total_sec
        phase_sec = max(0.0, next_sec - enter_sec)
        platform_total_sec += phase_sec
        platform_rows.append((p.get("name", "?"), phase_sec))
    for row_name, phase_sec in platform_rows:
        normalized = name_map.get(row_name, row_name)
        rec = vault_scan.get(normalized, {"total": 0, "has_transcript": 0})
        log_new = extras.get("platform_new_counts", {}).get(normalized)
        count = log_new if log_new is not None else rec["total"]
        lines.append(f"| {row_name} | {count} 篇 | {fmt_min(phase_sec)} | {fmt_pct(phase_sec, total_sec)} | 当前入口到下一入口的累计时间差 |")
    log_total = sum(extras.get("platform_new_counts", {}).values())
    lines.append(f"| **合计** | **{log_total or total_vault} 篇** | **{fmt_min(platform_total_sec)}** | **{fmt_pct(platform_total_sec, total_sec)}** | **与总墙钟闭合** |")
    lines.append("")

    # ── 三、按 OP 统计（与本地墙钟总时间闭合） ──
    lines.append("## 三、按 OP 统计（与本地墙钟闭合）")
    lines.append("")
    lines.append("> 这里统计“本地墙钟内实际记录到的单项耗时”。VM 转录为 handoff 之后的**异步阶段**，不计入本地墙钟，单独列在「五、VM 异步转录阶段」；绝不拿别的环节估算耗时。")
    lines.append("")
    lines.append("| OP 环节 | 处理篇数/次数 | 已记录耗时 | 占总墙钟 | 数据依据 |")
    lines.append("|---|---:|---:|---:|---|")
    audio_recs = extras.get("extract_audio_records", [])
    audio_sec = sum(r["total_s"] for r in audio_recs)
    if audio_recs:
        lines.append(f"| 音频抽取 | {len(audio_recs)} 次 | {fmt_min(audio_sec)} | {fmt_pct(audio_sec, total_sec)} | 日志 `[audio] 抽取完成 ... 总=...s` |")

    # VM 转录：异步阶段, 不计入本地墙钟 (见第五节)
    if vm_exists and vm_total:
        lines.append(f"| VM 转录（异步） | {vm_success} 篇 | 不在本地墙钟内（见第五节） | — | 本地 handoff 后由 VM daemon 异步完成，耗时见 crawl_op_vm_{report_date}.md |")
    else:
        lines.append(f"| VM 转录（异步） | — | 未记录（VM 报告缺失） | — | 未找到 crawl_op_vm_{report_date}.md，请确认已同步 |")

    measured_sec = audio_sec
    residual_sec = max(0.0, total_sec - measured_sec)
    lines.append(f"| 其他/未细分（抓取、发布、总结、等待等） | — | {fmt_min(residual_sec)} | {fmt_pct(residual_sec, total_sec)} | 总墙钟 − 已记录 OP |")
    lines.append(f"| **OP 合计（墙钟）** | — | **{fmt_min(measured_sec + residual_sec)}** | **100.0%** | **应与跑批总墙钟 {fmt_min(total_sec)} 一致** |")
    lines.append("")

    if not vm_exists:
        lines.append("> ⚠️ 未找到 VM 转录回执，VM 转录耗时未能并入。请确认 VM 报告 `crawl_op_vm_{report_date}.md` 已同步到 vault/04_agent/report/。")
        lines.append("")

    # ── 四、运行结果 ──
    lines.append("## 四、运行结果")
    lines.append("")
    lines.append(f"- 本批平台日志输出：{logged_output_total or total_vault} 篇；vault 扫描口径为 {total_vault} 篇，两者不一致时以本批日志为跑批产出依据。")
    if vm_exists:
        lines.append(f"- VM 转录（ASR 唯一路径）：本批 {vm_total} 篇，成功 {vm_success} 篇，失败 {vm_fail} 篇（详见 crawl_op_vm_{report_date}.md）。")
    lines.append(f"- Groq（legacy，已废弃）：成功 {n_groq_success} 篇，429 {len(extras['groq_429_records'])} 次，ASR.FATAL {len(extras['asr_fatal_records'])} 次。")
    if extras["asr_fatal_records"]:
        lines.append(f"- 失败音频已持久化到 `state/pending_audio/`，下次跑批自动补录。")
    lines.append("")

    # ── 五、VM 异步转录阶段（本地墙钟之外） ──
    lines.append("## 五、VM 异步转录阶段（本地墙钟之外）")
    lines.append("")
    if vm_exists:
        lines.append(f"> 3.1.0 起 ASR 唯一路径改为 VM：本地 handoff 音频后由 VM daemon 串行转录（FunASR + Zhipu GLM 总结）。以下为其处理窗口，与上方本地墙钟（{fmt_min(total_sec)}）不重叠、不闭合。")
        lines.append("")
        lines.append(f"- 本批转录篇数：**{vm_total}**（成功 {vm_success} / 失败 {vm_fail}；注：VM 报告为 daemon 当天转录总量，含历史 backfill，不全等于本次 run 的 handoff 数）")
        if vm_by_platform:
            lines.append("")
            lines.append("| 平台 | 成功 | 失败 | 累计处理耗时 |")
            lines.append("|---|---:|---:|---:|")
            for plat, rec in sorted(vm_by_platform.items()):
                lines.append(f"| {plat} | {rec['success']} | {rec['fail']} | {fmt_min(rec['cum_sec'])} |")
            lines.append(f"| **合计** | **{vm_success}** | **{vm_fail}** | **{fmt_min(vm_cum_sec)}** |")
        if vm.get("first_ts") and vm.get("last_ts"):
            lines.append("")
            lines.append(f"- VM 处理窗口（明细采样 {vm['detail_count']} 条）：`{vm['first_ts']}` → `{vm['last_ts']}`（墙钟跨度 {fmt_min(vm['span_sec'])}）")
            lines.append(f"- 说明：「累计处理耗时 {fmt_min(vm_cum_sec)}」是各篇转录 CPU 时长之和；「墙钟跨度 {fmt_min(vm['span_sec'])}」是 daemon 串行消化队列的真实时间，两者因队列间隙/并发不同而差异正常。")
    else:
        lines.append("> 未找到 VM 转录回执 `crawl_op_vm_{report_date}.md`，本阶段数据缺失。")
    lines.append("")
    return "\n".join(lines) + "\n"


# ════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description="自动生成 crawl 跑批报告 (sample_0726 风格)")
    p.add_argument("--date", required=True, help="日期 YYYYMMDD")
    p.add_argument("--log-path", default=None, help="指定历史日志路径（仅兼容旧批）")
    p.add_argument("--run-tag", default=None, help="指定本次跑批的唯一 run_tag")
    p.add_argument("--skill", default=str(CRAWL_ROOT), help="crawl skill 根路径")
    p.add_argument("--vault", default=str(VAULT_DEFAULT), help="vault 根路径")
    p.add_argument("--no-write", action="store_true", help="只打印到 stdout, 不写文件")
    args = p.parse_args()

    skill_root = Path(args.skill)
    vault_root = Path(args.vault)
    log_path = Path(args.log_path) if args.log_path else find_log(skill_root, args.date)

    print(f"📄 日志: {log_path}")
    truth = parse_truth(skill_root, log_path)
    extras = parse_log_extras(log_path)
    sup_json = parse_supervisor_json(skill_root)
    run_window = event_run_window(skill_root, args.run_tag) if args.run_tag else None
    start_iso, _, _ = run_window or detect_run_window(log_path)
    vault_scan = scan_vault_for_window(vault_root, start_iso, report_date=args.date) if start_iso else {}
    vm_report = parse_vm_report(vault_root, args.date)

    print(f"  📊 log 解析: {len(extras['platforms'])} 平台, {len(extras['groq_429_records'])} 次 429, "
          f"{len(extras['asr_fatal_records'])} 次 ASR.FATAL, {len(extras['groq_success_chars'])} 次 Groq 成功")
    print(f"  📁 vault 扫描: {sum(r['total'] for r in vault_scan.values())} 篇入库, "
          f"{sum(r['has_transcript'] for r in vault_scan.values())} 有正文")
    print(f"  🖥️  VM 回执: {'存在' if vm_report['exists'] else '缺失'} "
          f"(转录 {vm_report['total']} 篇, 累计 {vm_report['cum_sec']}s)")

    md = build_markdown(truth, extras, vault_scan, sup_json, args.date, log_path, run_window=run_window, run_tag=args.run_tag or "", vm=vm_report)

    if args.no_write:
        print(md)
        return 0

    # 写 truth.json
    truth_json = skill_root / "state" / "truth.json"
    truth_json.write_text(json.dumps({
        "truth": truth,
        "extras": extras,
        "supervisor_json": sup_json,
        "vault_scan": {k: {"total": v["total"], "has_transcript": v["has_transcript"]}
                       for k, v in vault_scan.items()},
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"  📄 truth.json: {truth_json}")

    # 写报告
    out_dir = vault_root / "04_agent" / "report"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"crawl_op_{args.date}.md"
    report_path.write_text(md, encoding="utf-8")
    print(f"  ✅ 报告已生成: {report_path}")
    print(f"     总字数: {len(md)}, 行数: {md.count(chr(10))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
