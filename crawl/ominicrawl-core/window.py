"""
common/window.py — 小红书抓取专用 Chrome 窗口管理 (纯 Python 版, 2026-07-08 从 crawl_all.sh 抽出)

设计原则:
  1. 工作窗口必须由本模块打开, 并带 --silent-debugger-extension-api
     (OpenCLI 扩展用 chrome.debugger API 控制页面, 不带此参数会显示"Chrome 正在被调试"横幅)
  2. 只开一个, 状态记 XHS_WIN_STATE, 便于复用和精准关闭(不动用户主 profile / 其他窗口)
  3. 复用已有窗口(状态文件记录的且还活着), 绝不叠开新窗口
  4. 开窗后把用户焦点窗口恢复到最前(防止抢走用户视线)
  5. 等 opencli 扩展连接(重试检查, 不开新窗口)

仅 macOS 使用 (依赖 osascript JXA + opencli)。
"""
import os
import re
import subprocess
import time
from pathlib import Path

OPENCLI = os.path.expanduser("~/.npm-global/bin/opencli")
XHS_WIN_STATE = Path("/tmp/xhs_work_win_id")
XHS_URL = "https://www.xiaohongshu.com"
CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


# ── 底层: osascript JXA 封装 ──────────────────────────────────────────────
def _osa(script: str) -> str:
    try:
        r = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", script],
            capture_output=True, text=True, timeout=15,
        )
        return (r.stdout or "").strip()
    except Exception:
        return ""


def _opencli(args, timeout=20):
    try:
        return subprocess.run(
            [OPENCLI, *args], capture_output=True, text=True, timeout=timeout
        )
    except Exception:
        return None


# ── 窗口枚举 / 清理 ───────────────────────────────────────────────────────
def snapshot_window_ids():
    """返回当前所有 Chrome 窗口 ID 列表(int)"""
    out = _osa(
        'var c=Application("Google Chrome"); '
        'c.windows().map(function(w){return w.id();}).join(",");'
    )
    return [int(x) for x in out.split(",") if x.strip().isdigit()]


def xhs_cleanup_old_windows():
    """清理残留的 about:blank / opencli-worker 窗口(不碰用户正常窗口)"""
    _osa(
        """
    var c = Application("Google Chrome");
    c.windows().forEach(function(w){
      try {
        var u = w.tabs[0].url();
        if (u.indexOf("opencli-worker") >= 0 || u === "about:blank") { w.close(); }
      } catch(e) {}
    });
    """
    )


def _win_alive(wid) -> bool:
    if not wid:
        return False
    return _osa(f'Application("Google Chrome").windows.byId({wid}) != null;').lower() == "true"


def _ext_connected() -> bool:
    """opencli 扩展是否已连接 (doctor 输出形如 '[OK] Extension: connected (v1.0.22)')"""
    r = _opencli(["doctor"])
    if not r:
        return False
    out = (r.stdout or "") + (r.stderr or "")
    return bool(re.search(r"Extension:\s*connected", out))


def _navigate(wid, url):
    _osa(
        f'var w=Application("Google Chrome").windows.byId({wid}); '
        f'if(w){{ w.tabs[0].url="{url}"; }}'
    )


def _restore_focus(user_app, user_win, work_win):
    """开窗后恢复用户焦点: 工作窗口沉到 Z 轴最后, 用户窗口提回最前"""
    if user_app == "Google Chrome" and user_win and work_win:
        _osa(
            f"""
        var c = Application("Google Chrome");
        var ww = c.windows.byId({work_win});
        if (ww) {{ try {{ ww.index = c.windows.length; }} catch(e) {{}} }}
        var uw = c.windows.byId({user_win});
        if (uw) {{ try {{ uw.index = 1; }} catch(e) {{}} }}
        """
        )
    elif user_app and user_app != "Google Chrome":
        _osa(
            f'var se=Application("System Events"); '
            f'var p=se.processes.byName("{user_app}"); if(p){{p.frontmost=true;}}'
        )


# ── 主接口 ───────────────────────────────────────────────────────────────
def ensure_one_window():
    """
    确保有且仅有一个 Profile 1 工作窗口, 返回窗口 ID(int); 失败返回 None。
    优先复用状态文件记录的窗口, 否则新开一个。
    """
    # 0. 记录用户当前焦点(用于事后恢复)
    user_app = _osa('Application("System Events").processes.whose({frontmost:true})[0].name();')
    user_win = None
    if user_app == "Google Chrome":
        try:
            user_win = int(_osa('Application("Google Chrome").windows[0].id();'))
        except (ValueError, TypeError):
            user_win = None

    # 1. 清理残留
    xhs_cleanup_old_windows()
    time.sleep(1)

    # 2. 复用已有窗口
    saved_id = None
    if XHS_WIN_STATE.exists():
        try:
            saved_id = int(XHS_WIN_STATE.read_text().strip())
        except Exception:
            saved_id = None
    if saved_id and _win_alive(saved_id):
        _navigate(saved_id, XHS_URL)
        for _ in range(5):
            if _ext_connected():
                return saved_id
            time.sleep(3)
        return saved_id  # 窗口在, 扩展稍后连上也行

    # 3. 新开窗口 (直接调 Chrome 二进制, 单例会转发 --profile-directory)
    before = set(snapshot_window_ids())
    subprocess.Popen(
        [CHROME_BIN, "--profile-directory=Profile 1",
         "--silent-debugger-extension-api", XHS_URL],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    new_id = None
    for _ in range(25):
        time.sleep(1)
        diff = [w for w in snapshot_window_ids() if w not in before]
        if diff:
            new_id = diff[0]
            break
    if new_id is None:  # 兜底再扫一遍
        diff = [w for w in snapshot_window_ids() if w not in before]
        if diff:
            new_id = diff[0]

    if not new_id:
        return None

    XHS_WIN_STATE.write_text(str(new_id))
    time.sleep(4)
    # 清理开 Profile 1 时附带的空白窗
    _osa(
        f"""
    var c = Application("Google Chrome");
    c.windows().forEach(function(w){{
      try {{
        var u = w.tabs[0].url();
        if ((u === "about:blank" || u === "chrome://newtab/" || u.indexOf("opencli-worker") >= 0) && w.id() != {new_id}) {{ w.close(); }}
      }} catch(e) {{}}
    }});
    """
    )
    # 兜底导航
    _navigate(new_id, XHS_URL)
    _restore_focus(user_app, user_win, new_id)

    for _ in range(5):
        if _ext_connected():
            return new_id
        time.sleep(3)
    return new_id


def close_window(wid=None):
    """关闭【本模块打开】的工作窗口(按参数或状态文件), 不动用户窗口"""
    if not wid and XHS_WIN_STATE.exists():
        try:
            wid = int(XHS_WIN_STATE.read_text().strip())
        except Exception:
            wid = None
    if wid:
        _osa(f'var w=Application("Google Chrome").windows.byId({wid}); if(w){{w.close();}}')
    if XHS_WIN_STATE.exists():
        XHS_WIN_STATE.unlink()


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ensure"
    if cmd == "ensure":
        wid = ensure_one_window()
        print(wid if wid else "")
    elif cmd == "close":
        w = sys.argv[2] if len(sys.argv) > 2 else None
        close_window(int(w) if w and w.isdigit() else None)
        print("closed")
    else:
        print("usage: window.py {ensure|close} [win_id]", file=sys.stderr)
        sys.exit(1)
