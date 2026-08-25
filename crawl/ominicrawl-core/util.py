"""
common/util.py — 跨平台通用小工具 (2026-07-08 统一自 5 份散落副本)

统一来源: 各平台散落的 sanitize/to_yymmdd/yml_escape/dedup/cache_load/cache_save/
fld/_parse_count/run_opencli, 以 xiaohongshu/crawl.py 最完整版为基准(含中文数字
_parse_count)。集中到此一处, 避免同一 bug(如 int('1.5万')) 在多份副本间反复出现。

cache 统一落到 paths.cache_file()(中央去重缓存), 解决此前 B站 bilibili_sub.json
与中央缓存分裂的问题。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

# 2026-07-21: 缓存读写加 fcntl 建议锁, 避免多进程/多任务并发写同一缓存文件
# (crawl watchlist 跑批 + clip 模式可能并行) 造成 json 半写损坏。
try:
    import fcntl
    _HAVE_FCNTL = True
except Exception:
    _HAVE_FCNTL = False

from datetime import datetime, timezone, timedelta
from pathlib import Path


def _with_lock(fp, mode="r", data=None):
    """对单个文件加 fcntl 建议锁后读/写, 降低并发损坏风险 (仅 Unix 有效)."""
    if not _HAVE_FCNTL:
        if mode == "w":
            Path(fp).write_text(data, encoding="utf-8")
            return
        return Path(fp).read_text(encoding="utf-8")
    import contextlib
    with open(fp, mode + ("+" if mode == "r" else ""), encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            if mode == "r":
                return f.read()
            else:
                f.seek(0)
                f.truncate()
                f.write(data)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

try:
    import yaml  # 可选: 部分 opencli 适配器(boss 等)用 YAML 输出, 失败时 fallback
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

from common.paths import cache_file

TZ = timezone(timedelta(hours=8))  # Asia/Shanghai (UTC+8)
DEFAULT_OPENCLI_PROFILE = os.environ.get("OPENCLI_PROFILE", "dy2s6y2k")

# 缓存文件句柄(模块级, 统一为中央缓存)
CACHE_FILE = cache_file()


def sanitize(s):
    if not s:
        return "untitled"
    s = re.sub(r"[\/:*?\"<>|\n\r]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"[ ._.,;:，。、；：]+$", "", s)
    return s[:80].strip() or "untitled"


def to_yymmdd(val):
    if not val:
        return datetime.now(TZ).strftime("%y%m%d")
    try:
        ts = int(val)
        if ts > 1e12:  # 毫秒 → 秒(自动识别, 兼容秒/毫秒两种输入)
            ts = ts / 1000
        return datetime.fromtimestamp(ts, TZ).strftime("%y%m%d")
    except Exception:
        return datetime.now(TZ).strftime("%y%m%d")


def yml_escape(s):
    if s is None:
        return ""
    s = str(s)
    s = re.sub(r"\s+", " ", s)
    if any(c in s for c in [":", '"', "#"]) or s.strip() != s:
        s = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{s}"'
    return s


def dedup(path):
    p = Path(path)
    if not p.exists():
        return p
    base, ext = p.stem, p.suffix
    i = 2
    while i < 100:
        cand = p.with_name(f"{base}_{i}{ext}")
        if not cand.exists():
            return cand
        i += 1
    return p


def cache_load():
    if CACHE_FILE.exists():
        try:
            return json.loads(_with_lock(CACHE_FILE, "r"))
        except Exception:
            return {}
    return {}


def cache_save(d):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _with_lock(CACHE_FILE, "w", json.dumps(d, ensure_ascii=False, indent=2))


def fld(v):
    if v is None:
        return None
    if isinstance(v, str) and not v.strip():
        return None
    return v


def _parse_count(v):
    """点赞/评论/收藏数转 int。支持中文单位: '1.5万'/'1.2w'/'3500'/'10+'/'0'。
    无法解析返回 0(不抛异常, 避免整博主抓取中断)。"""
    if v is None:
        return 0
    s = str(v).strip().replace("+", "").replace(" ", "")
    if not s:
        return 0
    mult = 1
    if s[-1] in "万Ww":
        mult = 10000
        s = s[:-1]
    elif s[-1] in "亿Yy":
        mult = 100000000
        s = s[:-1]
    try:
        return int(float(s) * mult)
    except Exception:
        return 0


def resolve_short_url(url, timeout=15, ua=None):
    """跟随重定向解析分享短链到最终长链。

    抖音/B站「复制链接」得到的是 v.douyin.com/xxx / b23.tv/xxx 短链,
    直接取不出 aweme_id / BV 号。本函数用移动端 UA 跟随 302 重定向,
    返回最终 URL (实测形如 https://www.iesdouyin.com/share/video/<aweme_id>/...
    或 https://m.bilibili.com/video/BVxxxx), 供 extract_aweme_id / extract_bvid 二次解析。
    解析失败返回原 URL(让下游按原逻辑报错, 不吞异常)。
    """
    import requests
    if ua is None:
        ua = ("Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
              "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 "
              "Mobile/15E148 Safari/604.1")
    try:
        r = requests.get(url, allow_redirects=True, timeout=timeout,
                         headers={"User-Agent": ua})
        return r.url
    except Exception as e:
        print(f"  [短链解析失败] {url} -> {e}")
        return url


def run_opencli(args, profile=DEFAULT_OPENCLI_PROFILE, timeout=60):
    """调 opencli 子命令, 返回 stdout; 失败/超时返回 None。"""
    bin_cand = os.path.expanduser("~/.npm-global/bin/opencli")
    bin_path = bin_cand if os.path.exists(bin_cand) else (shutil.which("opencli") or "opencli")
    cmd = [bin_path, "--profile", profile] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            print(f"  [opencli] fail ({' '.join(str(a) for a in args[:3])}...): {r.stderr.strip()[:200]}",
                  file=__import__("sys").stderr)
            return None
        return r.stdout
    except subprocess.TimeoutExpired:
        print(f"  [opencli] timeout: {' '.join(str(a) for a in args[:3])}", file=__import__("sys").stderr)
        return None
    except Exception as e:
        print(f"  [opencli] err: {e}", file=__import__("sys").stderr)
        return None


# ---------------------------------------------------------------------------
# opencli 浏览器桥健壮性 (2026-07-09 加固)
# 2026-07-21: 移除 NO_PROXY 注入 — VPN 软件按域名自动路由, localhost CDP 不走代理
# 保留瞬时错误重试机制 (本地问题: opencli rc=0 + 'ok: false' 误判)
# ---------------------------------------------------------------------------
_TRANSIENT_OPENCLI_MARKERS = (
    "ok: false",
    "code: UNKNOWN",
    "code: COMMAND_EXEC",   # 2026-07-17: Boss API 反爬/网络错
    "Network Error",        # 同上: opencli adapter 抛 xhr.onerror
    "stale page",
    "Detached while handling",
    "BROWSER_CONNECT",
    "Page not found",
)


def opencli_env() -> dict:
    """opencli 子进程环境副本. 2026-07-21: 不再注入 NO_PROXY — VPN 按域名自动路由.
    localhost/127.0.0.1 的 CDP 通信本来就不该走代理, 由 VPN 软件自行处理.
    """
    e = dict(os.environ)
    # 2026-07-15: LinkedIn 页面加载慢（60s+ captcha），默认 60s timeout 不够
    e.setdefault("OPENCLI_BROWSER_COMMAND_TIMEOUT", "300")
    return e


def is_transient_opencli_error(text: str) -> bool:
    """opencli 瞬时/可重试错误(stdout 含这些标记即重试)。"""
    return any(m in (text or "") for m in _TRANSIENT_OPENCLI_MARKERS)


def run_opencli_json(cmd, retries: int = 6, timeout: int = 120, delay: float = 5.0,
                     profile=None, retry_empty: bool = False):
    """运行 opencli 命令并返回解析后的 JSON(列表/字典); 瞬时错误自动重试。

    - 2026-07-21: 不再注入 NO_PROXY — VPN 软件按域名自动路由
    - opencli 失败常 rc=0 + 'ok: false' JSON, 需从 stdout 检测(而非只看 returncode)
    - 瞬时 CDP 错误(stale page / Detached / BROWSER_CONNECT)重试, 全失败返回 None
    - retry_empty=True 时, 解析为**空列表[]**也视为可疑(冷页面空解析), 重试; 全部重试后仍空则返回 [] (调用方跳过)
    调用方应把 None/[] 当作"本次无有效数据"处理(返回 [] 并跳过/记日志)。
    """
    bin_cand = os.path.expanduser("~/.npm-global/bin/opencli")
    bin_path = bin_cand if os.path.exists(bin_cand) else (shutil.which("opencli") or "opencli")
    full = [bin_path] + list(cmd) if not profile else [bin_path, "--profile", profile] + list(cmd)
    env = opencli_env()
    last = ""
    last_parsed = None
    for attempt in range(1, retries + 1):
        try:
            r = subprocess.run(full, capture_output=True, text=True, timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            last = f"timeout(尝试{attempt})"
            print(f"  [opencli] 超时(尝试{attempt}): {' '.join(str(c) for c in cmd[:3])}",
                  file=sys.stderr)
            time.sleep(delay)
            continue
        out = r.stdout or ""
        if r.returncode != 0:
            last = r.stderr[:200]
            print(f"  [opencli] rc={r.returncode}(尝试{attempt}): {r.stderr[:160]}",
                  file=sys.stderr)
            time.sleep(delay)
            continue
        if is_transient_opencli_error(out):
            last = out[:200]
            print(f"  [opencli] 瞬时CDP错误(尝试{attempt}): {out[:140]}", file=sys.stderr)
            time.sleep(delay)
            continue
        stripped = out.strip()
        data = None
        # 优先 JSON, 失败则 YAML 兜底(opencli boss 等适配器返 YAML)
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            if _HAS_YAML and stripped and not stripped.startswith("{") and ":" in stripped:
                try:
                    data = yaml.safe_load(stripped)
                except Exception as e:
                    last = f"YAML解析失败(尝试{attempt}): {e}"
                    print(f"  [opencli] JSON+YAML解析失败(尝试{attempt}): {stripped[:100]}",
                          file=sys.stderr)
                    time.sleep(delay)
                    continue
            if data is None:
                last = out[:100]
                print(f"  [opencli] JSON解析失败(尝试{attempt}): {out[:100]}", file=sys.stderr)
                time.sleep(delay)
                continue
        # 成功解析: 记录, 若开启空结果重试且为空列表则视为可疑再试
        last_parsed = data
        if retry_empty and isinstance(data, list) and not data:
            last = "空列表(尝试%d)" % attempt
            print(f"  [opencli] 空结果重试(尝试{attempt}): {' '.join(str(c) for c in cmd[:3])}",
                  file=sys.stderr)
            time.sleep(delay)
            continue
        return data
    if last_parsed is not None:
        print(f"  [opencli] 重试{retries}次后仍空: {last[:120]}", file=sys.stderr)
        return last_parsed
    print(f"  [opencli] 重试{retries}次仍失败: {last[:140]}", file=sys.stderr)
    return None
