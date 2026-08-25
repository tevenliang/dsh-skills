#!/usr/bin/env python3
# transcribe_daemon.py -- 带心跳、失败计数、退避的守护
import os, sys, json, time, signal, subprocess, datetime, fcntl, psutil, shutil
from pathlib import Path

BASE = Path(__file__).resolve().parent
INBOX = BASE / "inbox"
PROC = BASE / "processing"
DONE = BASE / "done"
FAILED = BASE / "failed"
STATUS = BASE / "status.jsonl"
HEARTBEAT = BASE / "worker.heartbeat"  # 心跳文件
VAULT_REPORT = (Path(os.environ.get("VAULT", "/home/ubuntu/webdav/steven_vault"))
                / "04_agent" / "report")
LOCK_FILE = Path("/tmp/crawl-transcribe.lock")
WORKER = BASE / "transcribe_worker.py"
PY = BASE / "venv" / "bin" / "python3"
GEN_TODAY = BASE / "gen_today.py"

POLL = 30  # daemon 轮询周期
HEARTBEAT_TIMEOUT = 600  # 心跳超时（10分钟没更新就认为卡死）
MAX_CONSECUTIVE_FAILURES = 3  # 连续失败次数上限
RESTART_BACKOFF = [30, 90, 300]  # 失败后等待时间（递增）
MEM_THRESHOLD_MB = 256
DONE_KEEP_DAYS = 7
REPORT_INTERVAL = 600

_worker_proc = None
_consecutive_failures = 0


def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _acquire_lock():
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.write(fd, str(os.getpid()).encode())
        return fd
    except (IOError, OSError):
        log("another daemon running, exit")
        sys.exit(0)


def _release_lock(fd):
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    except Exception:
        pass


def _kill_process_group(pid):
    try:
        parent = psutil.Process(pid)
        for c in parent.children(recursive=True):
            try: c.kill()
            except psutil.NoSuchProcess: pass
        parent.kill()
    except psutil.NoSuchProcess:
        pass
    except Exception as e:
        log(f"  kill 进程 {pid} 失败: {e}")


def start_worker():
    global _worker_proc
    if _worker_proc is not None and _worker_proc.poll() is None:
        return
    log(f"启动 worker: {PY} {WORKER}")
    try:
        env = dict(os.environ)
        env["VAULT"] = "/home/ubuntu/webdav/steven_vault"
        env["HOME"] = "/home/ubuntu"
        env["MODELSCOPE_CACHE"] = "/home/ubuntu/crawl-transcribe/models"
        _worker_proc = subprocess.Popen(
            [str(PY), str(WORKER)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
            env=env
        )
        log(f"worker started, pid={_worker_proc.pid}")
    except Exception as e:
        log(f"启动 worker 失败: {e}")


def stop_worker():
    global _worker_proc
    if _worker_proc is None:
        return
    try:
        _worker_proc.terminate()
        _worker_proc.wait(timeout=10)
    except Exception:
        try:
            _worker_proc.kill()
        except Exception:
            pass
    _worker_proc = None


def _worker_alive():
    """进程存活 + 心跳未超时"""
    if _worker_proc is None or _worker_proc.poll() is not None:
        return False
    if not HEARTBEAT.exists():
        # worker 还没写过心跳（刚启动在 init 阶段）→ 假定还活着，给 10 分钟宽限
        return True
    try:
        hb_mtime = HEARTBEAT.stat().st_mtime
        if time.time() - hb_mtime > HEARTBEAT_TIMEOUT:
            log(f"worker 心跳超时（{int(time.time()-hb_mtime)}s 没更新），判定卡死")
            return False
    except Exception:
        pass
    return True


def check_worker():
    """检查 worker，死了/卡死就重启，连续失败多就停止"""
    global _worker_proc, _consecutive_failures

    if _worker_alive():
        _consecutive_failures = 0  # 重置
        return

    # worker 出问题了
    _consecutive_failures += 1
    rc = _worker_proc.poll() if _worker_proc else None

    if _consecutive_failures > MAX_CONSECUTIVE_FAILURES:
        log(f"!! worker 已连续失败 {_consecutive_failures-1} 次（>={MAX_CONSECUTIVE_FAILURES}），停止自动重启")
        log(f"   请人工检查：funasr 模型、显存/内存、API key")
        log(f"   修复后手动执行：pkill -f transcribe_worker && rm -f {BASE}/worker.heartbeat && 重启 daemon")
        return

    # 退避等待
    backoff = RESTART_BACKOFF[min(_consecutive_failures - 1, len(RESTART_BACKOFF) - 1)]
    log(f"worker 异常 (rc={rc}, fail#{_consecutive_failures}/{MAX_CONSECUTIVE_FAILURES})，{backoff}s 后重启")

    # 强制 kill 残留
    if _worker_proc is not None:
        try:
            _kill_process_group(_worker_proc.pid)
        except Exception:
            pass
        try:
            _worker_proc.wait(timeout=5)
        except Exception:
            pass
        _worker_proc = None

    # 回收 processing 中的卡死文件
    recover_processing()

    # 清掉旧心跳文件
    try:
        HEARTBEAT.unlink()
    except Exception:
        pass

    # 检查内存够不够
    mem = psutil.virtual_memory()
    if mem.available < MEM_THRESHOLD_MB * 1024 * 1024:
        log(f"  内存仅 {mem.available//1024//1024}MB，跳过本次重启")
        return

    time.sleep(backoff)
    start_worker()


def recover_processing():
    leftovers = list(PROC.glob("*.wav")) + list(PROC.glob("*.mp3"))
    n = 0
    for w in leftovers:
        meta = w.with_suffix(".meta.json")
        try:
            shutil.move(str(w), str(INBOX / w.name))
            if meta.exists():
                shutil.move(str(meta), str(INBOX / meta.name))
            n += 1
        except Exception as e:
            log(f"  recover {w.name} 失败: {e}")
    if n:
        log(f"recovery: 回收 {n} 个到 inbox")


def cleanup_done():
    cutoff = time.time() - DONE_KEEP_DAYS * 86400
    n = 0
    for f in DONE.iterdir():
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                n += 1
        except Exception:
            pass
    if n:
        log(f"清理 done/ 超期 {n} 个")


def write_report():
    today = datetime.datetime.now()
    today_str = today.strftime("%Y%m%d")
    today_prefix = today.strftime("%Y-%m-%d")
    lines = []
    if STATUS.exists():
        for ln in STATUS.read_text(encoding="utf-8").splitlines():
            try:
                lines.append(json.loads(ln))
            except Exception:
                pass
    today_lines = [l for l in lines if (l.get("ts") or "").startswith(today_prefix)]
    n_total = len(today_lines)
    n_ok = sum(1 for l in today_lines if l.get("ok"))
    by_plat = {}
    for l in today_lines:
        p = l.get("platform", "?")
        d = by_plat.setdefault(p, {"ok": 0, "fail": 0, "dur": 0.0})
        d["ok" if l.get("ok") else "fail"] += 1
        d["dur"] += float(l.get("dur") or 0)

    plat_names = ", ".join(sorted(by_plat)) if by_plat else "无"
    ok_icon = chr(10004) + chr(65039)
    fail_icon = chr(10060)
    hb_status = "OK"
    if HEARTBEAT.exists():
        age = int(time.time() - HEARTBEAT.stat().st_mtime)
        hb_status = f"OK ({age}s ago)" if age < HEARTBEAT_TIMEOUT else f"STALE ({age}s)"

    md = [
        f"# crawl_op_vm_{today_str} 运行回执", "",
        "## 基本信息",
        f"- 日期: {today_str}",
        f"- 处理平台: {plat_names}",
        f"- 本批转录篇数: {n_total}",
        f"- 成功/失败: {n_ok}/{n_total - n_ok}",
        f"- 连续失败次数: {_consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}",
        f"- worker 心跳: {hb_status}", "",
        "## 按平台统计",
        "| 平台 | 成功 | 失败 | 累计耗时 |",
        "|------|------|------|----------|",
    ]
    for p, s in sorted(by_plat.items()):
        md.append(f"| {p} | {s['ok']} | {s['fail']} | {s['dur']:.0f}s |")
    md += ["", "## 明细（最近 30 条）"]
    for l in today_lines[-30:]:
        icon = ok_icon if l.get("ok") else fail_icon
        md.append(f"- `{l.get('ts')}` [{l.get('platform')}] {l.get('video_id')} {icon} {str(l.get('detail',''))[:120]}")
    md.append("")
    try:
        VAULT_REPORT.mkdir(parents=True, exist_ok=True)
        out = VAULT_REPORT / f"crawl_op_vm_{today_str}.md"
        out.write_text("\n".join(md), encoding="utf-8")
    except Exception as e:
        log(f"  write_report failed: {e}")


def check_memory():
    mem = psutil.virtual_memory()
    avail_mb = mem.available / (1024 * 1024)
    if avail_mb < MEM_THRESHOLD_MB:
        log(f"可用内存 {avail_mb:.0f}MB < {MEM_THRESHOLD_MB}MB，暂停 60s")
        time.sleep(60)
    return avail_mb


def regenerate_indices(days=2):
    from datetime import date, timedelta
    today = date.today()
    for i in range(days):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        try:
            r = subprocess.run([sys.executable, str(GEN_TODAY), d],
                               capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                log(f"index {d} done")
        except Exception as e:
            log(f"  index {d} failed: {e}")


def main():
    for d in (INBOX, PROC, DONE, FAILED):
        d.mkdir(parents=True, exist_ok=True)
    recover_processing()
    start_worker()
    log(f"daemon 启动 poll={POLL}s mem={MEM_THRESHOLD_MB}MB "
        f"heartbeat_timeout={HEARTBEAT_TIMEOUT}s max_fail={MAX_CONSECUTIVE_FAILURES}")
    last_report = 0
    last_was_busy = False

    while True:
        try:
            check_memory()
            check_worker()
            pairs = list(INBOX.glob("*.wav")) + list(INBOX.glob("*.mp3"))
            if pairs:
                log(f"inbox {len(pairs)} 待处理")
                last_was_busy = True
            else:
                if last_was_busy:
                    log("queue empty, rebuild index")
                    regenerate_indices(days=2)
                    last_was_busy = False
            if time.time() - last_report > REPORT_INTERVAL:
                cleanup_done()
                write_report()
                last_report = time.time()
        except KeyboardInterrupt:
            log("SIGINT, stop worker")
            stop_worker()
            break
        except Exception as e:
            log(f"loop exception: {e}")
            time.sleep(5)
        time.sleep(POLL)


if __name__ == "__main__":
    lock_fd = _acquire_lock()
    main()
    _release_lock(lock_fd)
