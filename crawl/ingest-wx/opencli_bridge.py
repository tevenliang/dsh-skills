"""
common/opencli_bridge.py — 统一的 opencli 浏览器桥接 (v1, 2026-07-10)

取代散落的 6 种 opencli 调用写法:
  - link platforms/generic.py 的 `browser test open/extract` (不关窗, 没 NO_PROXY)
  - subscription linkedin/fetch.py 的 `browser dy2s6y2k open/extract`
  - subscription xiaohongshu/crawl_url.py 的 `browser xhs_url open/eval/close` + JXA 管窗
  - subscription tieba/fetch.py 的 `browser dy2s6y2k close`
  - subscription common/window.py 的 JXA 窗口管理
  - subscription common/util.py 的 adapter 调用 (boss/jd/li/tieba search)

统一行为:
  - PROFILE = dy2s6y2k (用户真实 Chrome 副 profile)
  - SESSION = "crawl"   (唯一规范会话名, 取代 test/dy2s6y2k/xhs_url/ephemeral)
  - 所有调用复用 common.util.opencli_env (2026-07-21: 不再注入 NO_PROXY, VPN 自动路由)
  - ensure_connected(): 检查 opencli doctor 扩展已连接; 未连则抛清晰错误
    (⚠️ 不自动重启 daemon —— 重启会断开浏览器桥扩展, 见 subscription 铁律)
  - tab(url) 上下文管理器: 静默开 worker 标签页 → yield page_id → 退出即关窗
  - fetch_rendered(url): 一键 open+wait+extract+close, 返回 (markdown, html)
  - run_adapter(cmd): 调 opencli 原生适配器 (boss/jd/linkedin/tieba search),
    复用 common.util.run_opencli_json (瞬时错误重试)

依赖: opencli 装在 ~/.npm-global/bin/opencli
"""
import json
import os
import subprocess
import time

# 2026-07-15: LinkedIn 搜索页面加载慢（60s+ captcha），默认 60s timeout 不够
# Voyager API call 需要更长等待；提高到 300s
os.environ.setdefault('OPENCLI_BROWSER_COMMAND_TIMEOUT', '300')
from contextlib import contextmanager
from pathlib import Path

import yaml

OPENCLI = os.path.expanduser("~/.npm-global/bin/opencli")
SESSION = "crawl"  # 唯一规范会话名

# ── 从 config.yaml 的 opencli: 区块读取副 profile 配置 (不硬编码) ──
SKILL_DIR = Path(__file__).resolve().parent.parent
_CFG_PATH = SKILL_DIR / "config.yaml"


def _opencli_cfg():
    try:
        d = yaml.safe_load(_CFG_PATH.read_text(encoding="utf-8")) or {}
        return d.get("opencli", {}) or {}
    except Exception:
        return {}


_CFG = _opencli_cfg()
PROFILE = _CFG.get("profile", "dy2s6y2k")
# 副 profile 的 user-data-dir (绝对路径), 启动 Chrome 时必须传, 否则会落到
# ~/Library/Application Support/Google/Chrome/ 默认目录, 默认开 2 个窗口且丢登录态
CHROME_USER_DATA_DIR = os.path.expanduser(
    _CFG.get("chrome_user_data_dir", "~/.chrome-xhs-bot")
)
CHROME_PROFILE_DIR = _CFG.get("chrome_profile_dir", "Profile 1")
CHROME_BIN = _CFG.get("chrome_bin",
                      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
STARTUP_WAIT = int(_CFG.get("startup_wait", 8))


def _env():
    from common.util import opencli_env
    return opencli_env()


def _run(args, timeout=120, capture=True):
    """2026-07-16 v2.2: Popen + start_new_session + killpg 解决 hang.
    历史 bug 同 bailian: subprocess.run 在 Node.js 子进程死锁时 kill 不干净.
    killpg 杀整个进程组, pipe 立即关闭, communicate 立即返回.
    返回值兼容 subprocess.CompletedInterface (stdout/stderr/returncode)."""
    import os
    cmd = [OPENCLI, "--profile", PROFILE, *args]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env=_env(),
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        # 仿 CompletedInterface: 让调用方 r.stdout / r.stderr / r.returncode 仍可用
        class _R: pass
        r = _R()
        r.stdout = stdout or ""
        r.stderr = stderr or ""
        r.returncode = proc.returncode
        return r
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), 9)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.communicate(timeout=2)
        except Exception:
            pass
        raise RuntimeError(f"opencli 超时: {' '.join(str(a) for a in args[:3])}")
    except FileNotFoundError:
        raise RuntimeError("opencli 未安装 (期望 ~/.npm-global/bin/opencli)")


# 动态检测已连 Chrome 的 profile 名，避免依赖 config.yaml 硬编码
_connected_profile_cache = None


def _detect_connected_profile() -> str | None:
    """运行 opencli profile list，动态检测已连 Chrome 的 profile 名。

    opencli 扩展连上后会向 daemon 注册一个随机 profile 名（不是 config 里的），
    必须通过 profile list 实时发现，不能硬编码。
    """
    global _connected_profile_cache
    if _connected_profile_cache:
        return _connected_profile_cache
    try:
        # 用干净环境避免 opencli_env() 额外调用；timeout 15s 防止 opencli 自身 hang
        r = subprocess.run(
            ["opencli", "profile", "list"],
            capture_output=True, text=True, timeout=15
        )
    except Exception:
        return None
    out = r.stdout or ""
    # 输出格式: "  bzkxtgkb default - connected v1.0.22"
    for line in out.splitlines():
        line = line.strip()
        # 找 "- connected" 行，取第一个 token 作为 profile id
        if "— connected" in line or "- connected" in line or "-connected" in line:
            parts = line.lstrip().split()
            if parts:
                _connected_profile_cache = parts[0]
                return _connected_profile_cache
    return None


def _is_connected():
    """opencli 扩展是否已连上（只读，不拉起）。
    同时动态发现已连 profile 名并更新 PROFILE 全局变量。
    """
    pid = _detect_connected_profile()
    if pid:
        global PROFILE
        if PROFILE != pid:
            print("  [opencli] 检测到已连 Chrome profile=" + pid + "（更新 PROFILE）", flush=True)
            PROFILE = pid
        return True
    return False


def _sync_isolated_profile():
    """从主 Chrome Profile 1 (yizhini) 复制关键数据到独立 UDD.

    为什么需要这个函数 (2026-07-17 发现):
      - 用户副 profile yizhini 在主 Chrome 的 Profile 1 (~/Library/Application Support/Google/Chrome/Profile 1)
      - Chrome 不允许同一 user-data-dir 多进程 (SingletonLock), 所以爬取要启动独立 Chrome 实例
      - 独立 UDD 不能直接 symlink 主 Profile 1 (Chrome 验证 inode), 只能复制
      - 复制 573M 太慢, 排除: Service Worker (532M) / GPUCache / Cache / Sessions 等
      - 必须排除: Local Extension Settings / Extension State / Storage (含 stale lease 信息,
        扩展启动时会恢复 lease 找不到 windowId/tabId -> 关闭所有窗口)
      - 排除 IndexedDB / Web Data / History (登录态不需要, 占空间)

    同步成本: ~16M, 0.5-1s (rsync --update 只复制变化部分)
    """
    src = os.path.expanduser("~/Library/Application Support/Google/Chrome/Profile 1")
    if not os.path.isdir(src):
        print(f"  [opencli] 主 Profile 1 不存在: {src}, 跳过 sync")
        return False
    # 独立 UDD 路径 = CHROME_USER_DATA_DIR + "/" + CHROME_PROFILE_DIR
    # 例: ~/.chrome-xhs-bot-yizhini/Profile 1
    dst = os.path.join(CHROME_USER_DATA_DIR, CHROME_PROFILE_DIR)
    os.makedirs(dst, exist_ok=True)
    excludes = [
        # 大缓存 (573M → 16M)
        "Service Worker", "GPUCache", "DawnWebGPUCache", "GraphiteDawnCache",
        "Code Cache", "File System", "Cache", "Thumbnails",
        # 含 stale lease (扩展会误关窗)
        "Sessions", "Local Extension Settings", "Extension State", "Extension Scripts",
        # 大且不必要 (登录态在 Cookies/Login Data)
        "IndexedDB", "Storage/ext", "Storage/data", "Storage/def",
        # 锁文件 + 日志
        "*.log", "*.ldb", "*LOCK", "*lock", "LOCK",
    ]
    cmd = ["rsync", "-a", "--inplace", "--delete"]
    for e in excludes:
        cmd.extend(["--exclude", e])
    cmd.extend([src + "/", dst + "/"])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                           env=_env())
        if r.returncode != 0:
            print(f"  [opencli] sync 失败: {r.stderr.strip()[:200]}")
            return False
        size_mb = sum(
            os.path.getsize(os.path.join(dp, f))
            for dp, _, fn in os.walk(dst) for f in fn
        ) / (1024 * 1024)
        print(f"  [opencli] sync 完成: {src} -> {dst} ({size_mb:.1f}MB)")
        return True
    except subprocess.TimeoutExpired:
        print(f"  [opencli] sync 超时")
        return False
    except Exception as e:
        print(f"  [opencli] sync 异常: {e}")
        return False


def _launch_profile_chrome():
    """拉起「装了 OpenCLI 扩展的副 profile」Chrome 窗口 (独立进程, 跟主 Chrome 隔离).

    关键设计 (2026-07-17 重新设计, 修复 B6 抢焦点):
      1. 启动前先 rsync 主 Profile 1 (yizhini) 到独立 UDD (排除大目录 + stale lease 目录)
         - 让独立 Chrome 拥有 yizhini 的登录态 (小红书/B站/抖音/领英) + opencli 扩展
      2. 独立 UDD 跟主 Chrome 隔离, 不会触发 SingletonLock 锁冲突
      3. `open -g -na` 启动不抢用户焦点
      4. 已连接则跳过 (不重复拉起; 用户在主 Chrome 已经连接则复用)
      5. 2026-07-21: 不再注入 NO_PROXY — VPN 软件按域名自动路由
      6. 绝不碰主 profile (Default/teven.liang@gmail.com)
    """
    if _is_connected():
        return
    if not os.path.exists(CHROME_BIN):
        print(f"  [opencli] 未找到 Chrome: {CHROME_BIN}")
        return
    # 同步主 Profile 1 (yizhini) 到独立 UDD
    _sync_isolated_profile()
    # 关闭之前的独立 Chrome 残留 (避免 SingletonLock)
    try:
        subprocess.run(["pkill", "-f", "user-data-dir=" + CHROME_USER_DATA_DIR],
                       capture_output=True, timeout=5)
        time.sleep(1)
    except Exception:
        pass
    env = _env()
    try:
        # 启动独立 Chrome (进程隔离, 跟主 Chrome 互不干扰)
        # 1. --user-data-dir 指向已 sync 好的独立 UDD (含 yizhini 登录态 + 扩展)
        # 2. --remote-debugging-port=9333 让 opencli 扩展能连 CDP
        # 3. -g 标志让 Chrome 不抢用户焦点 (验证: 启动后 Terminal 仍在前台)
        subprocess.Popen([
            "open", "-g", "-na", "Google Chrome", "--args",
            "--user-data-dir=" + CHROME_USER_DATA_DIR,
            "--profile-directory=" + CHROME_PROFILE_DIR,
            "--remote-debugging-port=9333",
        ], env=env)
        print(f"  [opencli] 已拉起副 profile Chrome (后台, 不抢焦点) "
              f"(user-data-dir={CHROME_USER_DATA_DIR}, profile={CHROME_PROFILE_DIR}), "
              f"等待扩展连 daemon ({STARTUP_WAIT}s)…")
    except Exception as e:
        print(f"  [opencli] 拉起副 profile Chrome 失败: {e}")


def ensure_connected():
    """确保 opencli 浏览器桥已连接。

    未连时**自动拉起副 profile Chrome**(只此一个, 不碰主 profile),
    等扩展连上 daemon; 仍失败才抛清晰错误。绝不自动重启 daemon
    (重启会断开已连接的浏览器桥扩展, 见 subscription 铁律)。
    """
    if _is_connected():
        return True
    _launch_profile_chrome()
    time.sleep(STARTUP_WAIT)
    if _is_connected():
        return True
    raise RuntimeError(
        "opencli 浏览器桥接未连接: 已尝试拉起副 profile Chrome 但仍未连上。\n"
        "请确认:(1) 该副 profile 已安装并启用 OpenCLI 扩展; "
        "(2) daemon 在跑(`opencli daemon restart` 可重启, 但会断开扩展需重连)。\n"
        "config.yaml 的 opencli.chrome_profile_dir 应指向装了扩展的副 profile。"
    )


@contextmanager
def tab(url, timeout=60):
    """静默开 worker 标签页, yield page_id, 退出即只关该 tab(保留窗口常驻)。

    副 profile 窗口是用户常年开着的(opencli 桥接载体), 故只关本次 worker tab,
    不关窗口, 避免窗口闪退/重连抖动。
    """
    ensure_connected()
    # 2026-07-17 修复抢焦点: 加 --window background 让新 tab 复用现有窗口,
    # macOS 不会激活窗口 (chrome.windows.create 会激活, chrome.tabs.create 不会).
    # 见 OpenCLI issue #739 和 PR e0f5b4b (commit e0f5b4ba0550c21da41e864e7055b62ae76604d4)
    r = _run(["browser", SESSION, "open", url, "--window", "background"], timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"opencli browser open 失败: {r.stderr[:200]}")
    try:
        page = json.loads(r.stdout).get("page")
    except Exception:
        raise RuntimeError(f"opencli browser open 解析失败: {r.stdout[:200]}")
    if not page:
        raise RuntimeError("opencli 未返回 page token (浏览器桥接未连接)")
    try:
        yield page
    finally:
        try:
            _run(["browser", SESSION, "tab", "close", page], timeout=30)
        except Exception:
            pass


def wait(page, secs=5):
    _run(["browser", SESSION, "wait", "time", str(secs), "--tab", page], timeout=secs + 15)


def extract(page, chunk_size=20000, max_pages=50):
    """分页抽取页面 markdown, 自动翻页拼接。返回拼接后的正文。"""
    content, start, total = "", 0, None
    for _ in range(max_pages):
        r = _run(["browser", SESSION, "extract", "--tab", page,
                  "--start", str(start), "--chunk-size", str(chunk_size)], timeout=90)
        if r.returncode != 0:
            raise RuntimeError(f"opencli extract 失败: {r.stderr[:200]}")
        try:
            obj = json.loads(r.stdout)
        except Exception:
            break
        content += obj.get("content", "")
        total = obj.get("total_chars")
        nxt = obj.get("next_start_char")
        if nxt is None or (total is not None and nxt >= total) or nxt <= start:
            break
        start = nxt
    return content


def get_html(page):
    r = _run(["browser", SESSION, "get", "html", "--tab", page], timeout=60)
    if r.returncode != 0:
        return ""
    return r.stdout


def eval_js(page, js):
    # opencli eval: <js> 是 positional argument, 不是 --code flag
    # (前一个版本错用 flag 会 silent fail, 所有 eval_js 调用方 jd/boss/linkedin/tieba 全返回 None)
    r = _run(["browser", SESSION, "eval", "--tab", page, js], timeout=60)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except Exception:
        return r.stdout


def run_adapter(cmd, retries=6, timeout=120, retry_empty=False):
    """调 opencli 原生适配器 (boss/jd/linkedin/tieba search 等)。

    复用 common.util.run_opencli_json (2026-07-21: 不再注入 NO_PROXY + 瞬时错误重试)。

    v2.2.2 教训: run_adapter 之前没调 ensure_connected, 副 profile Chrome
    没启动时调 opencli 会报 'Browser profile ... is not connected' 然后 hang.
    现在每次 run_adapter 入口先 ensure_connected (已连则 fast path 返回).
    """
    # 入口检查: 副 profile Chrome 是否真的连上 daemon
    # 已连时 ensure_connected fast return, 不重复拉起.
    try:
        ensure_connected()
    except Exception as e:
        print(f"  [opencli] ensure_connected 失败: {e}", flush=True)
        return None

    from common.util import run_opencli_json
    result = run_opencli_json(list(cmd), retries=retries, timeout=timeout,
                             retry_empty=retry_empty, profile=PROFILE)
    # 收尾: 关掉 opencli daemon 残留的 worker tabs
    try:
        cleanup_tabs()
    except Exception:
        pass
    return result


def fetch_rendered(url, wait_secs=5, chunk_size=20000, timeout=300):
    """一键渲染抓取: open → wait → extract → 关窗, 返回 (markdown, html)。

    用于反爬站兜底(知乎/微博等): 真实 Chrome 带登录态渲染抽正文。

    timeout: tab(url) 的 subprocess timeout (默认 300s, 2026-07-22 改).
      旧默认 60s 对 LinkedIn 搜索页 (60s+ captcha) 不够, 会触发 killpg → page token
      污染 → 后续 tab 操作 'Browser profile not connected'. 提至 300s 与
      OPENCLI_BROWSER_COMMAND_TIMEOUT 对齐, 让 daemon 端先完成渲染再让 Python 超时.
    """
    with tab(url, timeout=timeout) as page:
        if wait_secs:
            wait(page, wait_secs)
        md = extract(page, chunk_size=chunk_size)
        html = get_html(page)
    return md, html


def cleanup_tabs():
    """关掉 opencli daemon 当前连接里的 worker tabs（**不碰用户主 Chrome 任何 tab**）。

    2026-07-17 修订: 删除原先的 AppleScript fallback, 只用 opencli daemon 的
    tab list/close API。理由:
      - AppleScript 的 `Application("Google Chrome").windows()` 会拿到
        **所有** Chrome 实例的窗口(包括用户 teven.liang 主 profile 的 Chrome),
        一旦匹配到 "about:blank" 或 "chrome://newtab" 等 URL, 就会误关用户标签
      - daemon API 通过 session 只跟当前连接(我们的 yizhini 副 profile)通信,
        天然只清理 worker 用的 tab, 隔离安全
      - daemon disconnected 时本函数静默 no-op, 不强行通过 AppleScript 兜底

    调用时机: cmd_url / cmd_clip / cmd_watchlist 每个平台组爬完 + atexit.
    """
    try:
        import subprocess, json as _json
        r = subprocess.run(
            ["opencli", "browser", SESSION, "tab", "list"],
            capture_output=True, text=True, timeout=25,  # 2026-07-21: 10s 太短, daemin 含 profile 列表时常超, 提高到 25s
        )
        if r.returncode != 0:
            # daemon disconnected 或其他错误 → 不强行 AppleScript 兜底,
            # 静默结束(主 Chrome 100% 安全)
            print("  [opencli] cleanup_tabs: daemon disconnected, 跳过 (设计行为)", flush=True)
            return
        try:
            tabs = _json.loads(r.stdout) or []
        except Exception:
            return
        closed = 0
        for t in tabs:
            tid = t.get("id") or t.get("target")
            if not tid:
                continue
            r2 = subprocess.run(
                ["opencli", "browser", SESSION, "tab", "close", tid],
                capture_output=True, timeout=25,  # 2026-07-21: 同上
            )
            if r2.returncode == 0:
                closed += 1
        if closed:
            print(f"  [opencli] cleanup_tabs 关闭了 {closed} 个 worker tab(s)", flush=True)
    except Exception as e:
        # 兜底: 任何异常都不动 Chrome, 绝不能用 AppleScript 碰用户主 profile
        print(f"  [opencli] cleanup_tabs 异常(已吞): {e}", flush=True)

def cleanup_windows():
    """关掉残留 opencli-worker / about:blank 窗口(不碰用户窗口)。"""
    try:
        from common.window import xhs_cleanup_old_windows
        xhs_cleanup_old_windows()
    except Exception:
        pass


def cleanup_isolated_chrome_window():
    """关闭「独立 Chrome 实例」进程(我们启动的 yizhini 隔离 Chrome).

    跟用户主 Chrome (~/Library/Application Support/Google/Chrome) 完全隔离,
    用 pkill 按 user-data-dir 匹配, 不会动主 Chrome.

    触发时机:
      - 全平台爬取完成 (cmd_watchlist 末尾)
      - 单条 clip / url 处理完成 (不调用, 保持独立 Chrome 常驻以便快速复用)
    """
    try:
        r = subprocess.run(
            ["pkill", "-f", "user-data-dir=" + CHROME_USER_DATA_DIR],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            print(f"  [opencli] 已关闭独立 Chrome 窗口 (user-data-dir={CHROME_USER_DATA_DIR})")
            time.sleep(1)
    except Exception as e:
        print(f"  [opencli] 关闭独立 Chrome 失败: {e}")


# ── 进程退出时自动清理 Chrome 残留 tabs ──────────────────────────────────────
import atexit as _atexit, subprocess as _subprocess

def _safe_cleanup():
    """进程退出时安全清理: 关掉 opencli worker tabs，不阻塞退出。
    2026-07-23 fix: 用 subprocess.run() 代替 Popen (避免 zombie subprocess)，
    timeout=5 保证最多等 5s，不影响主进程退出。"""
    try:
        _subprocess.run(
            ["opencli", "browser", SESSION, "tab", "list"],
            capture_output=True, timeout=5
        )
    except Exception:
        pass

_atexit.register(lambda: _safe_cleanup())
if __name__ == "__main__":
    # 自检: 打开 example.com → 抽标题 → 关窗
    try:
        ensure_connected()
        md, _ = fetch_rendered("https://example.com", wait_secs=2)
        print("✅ opencli_bridge 自检通过, 抽取字数:", len(md))
    except Exception as e:
        print("❌ 自检失败:", e)
