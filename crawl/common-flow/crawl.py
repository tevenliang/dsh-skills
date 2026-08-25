import sys, os
import subprocess
_here = os.path.dirname(os.path.abspath(__file__))
while _here and not os.path.exists(os.path.join(_here, "_bootstrap.py")):
    _p = os.path.dirname(_here)
    if _p == _here:
        _here = None
        break
    _here = _p
if _here:
    sys.path.insert(0, _here)
import _bootstrap

# 2026-07-24: 注入 Supervisor 恢复钩子 (必须在 transcribe/summarize 第一次调用之前)
# 让 crawl.py 在被 supervisor.py 启动时, 自动读 recovery.json 决定 provider 行为
# - groq/bailian/mlx 已 disabled → 跳过该 provider
# - mlx degraded → 缩短超时
# - GLM 退避中 → 抛错让 summarize 跳过该条
try:
    from common_supervisor._injection import install_recovery_hooks
    install_recovery_hooks()
except Exception as _inj_err:
    print(f"  [supervisor-injection] 跳过 (启动失败): {_inj_err}", flush=True)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
crawl.py — ominicrawl 统一入口 (ominicrawl v1)

子命令:
  crawl url <URL> [--author X] [--title Y]
        单条链接 → 收件 $VAULT/subscription/<平台>/<博主>/hot.md (含总结)
  crawl clip [--dry-run]
        读 vault/01_my_notes/clip/*.md 队列, 逐条抓取→成功后删行+cache; 不支持/失败保留
  crawl watchlist [--date YYYYMMDD]
        读本地 Watchlist(博主清单 + 京东/Boss/领英/贴吧 关键词, vault 根 watchlist.md):
          · bilibili/douyin → 展开博主最新视频 → 逐条 转录+总结+聚合推 vault
          · xiaohongshu → xhs-cli API 批量抓博主笔记 → 直接追加 vault subscription/xiaohongshu-hot.md
          · boss/jd/linkedin/tieba → 关键词搜索 → 原始单文件 聚合推 vault
          · wechat monitor=false → 跳过(仅剪藏)
  crawl set-tool <platform> <tool>
        切换某平台抓取工具 (写回 config.yaml tools:)
  crawl tools
        打印当前 平台→工具 映射

来源层:
  - clip 读 clipboard 队列 (common/clipboard.py)
  - watchlist 读本地 vault watchlist.md (common/feishu_watchlist.py, 2026-07-19 脱飞书)
  - 流水线/推送: pipeline/run.py → common/publish_vault.py (落 $VAULT/subscription)
"""
import argparse
import faulthandler
import json
import os
import re
import shutil
import signal
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent  # = crawl/

# 进度监控
sys.path.insert(0, str(SKILL_DIR))
try:
    from common.progress_tracker import init_tracker, get_tracker
    _PROGRESS = True
except Exception:
    _PROGRESS = False
    def init_tracker(x): pass
    def get_tracker(): return None
for _p in (str(SKILL_DIR), str(SKILL_DIR / "common"), str(SKILL_DIR / "tools"),
          str(SKILL_DIR / "pipeline"), str(SKILL_DIR / "bilibili"),
          str(SKILL_DIR / "lib" / "douyin_api")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.clipboard import (read_clip_text, extract_urls, remove_url_from_note,
                                    canonical_key)
from common.opencli_bridge import (cleanup_tabs,
                                              cleanup_isolated_chrome_window)  # 爬取完成后自动关 Chrome 残留 tabs + 关独立 Chrome 窗口
from common.feishu_watchlist import get_watchlist_markdown, parse_rows
from common.registry import show_tools, set_tool, can_monitor
from common.util import cache_load as _cache_load_local, cache_save as _cache_save_local
# 2026-08-24: 统一缓存到VM端，Mac不再维护本地cache
# 改走 publish_vault 的 _load_state / _save_state（已SSH到VM）
from common.publish_vault import _load_state as _cache_load_local, _save_state as _cache_save_local
def cache_load(): return _cache_load_local()
def cache_save(d): _cache_save_local(d)

# ═══════════════════════════════════════════════════════════════
# 2026-08-12 fix: 去重完整性检查
# 原去重只看 cache(vid 列表)。空壳笔记(有 frontmatter 无 ## 转录)一旦写入 cache 就被永久跳过,
# 导致视频永远缺正文。改为: 视频平台需该 vid 的 md 存在且有 ## 转录 才算"已处理", 否则重抓补转录。
# ═══════════════════════════════════════════════════════════════
_VAULT_ROOT = Path(os.environ.get("VAULT", "/Users/tianwenliang/Documents/steven_vault"))
_VIDEO_VID_INDEX = {}  # plat -> {vid: is_complete}

def _extract_vid_from_url(url: str):
    """从视频 URL 提取 id (抖音=数字串, B站=BVxxx), 与 md source_url 提取规则一致"""
    if not url:
        return None
    m = re.search(r"douyin\.com/video/(\d+)", url) or re.search(r"bilibili\.com/video/(BV\w+)", url)
    return m.group(1) if m else None

def _ensure_vid_index(plat: str):
    """懒加载: 扫描 subscription/<plat>/ 下所有 md, 建 {vid: 有##转录} 索引 (视频平台用, run 内只建一次)"""
    if plat in _VIDEO_VID_INDEX:
        return
    idx = {}
    sub = _VAULT_ROOT / "subscription" / plat
    if sub.exists():
        for md in sub.rglob("*.md"):
            try:
                text = md.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            m = re.search(r"source_url:\s*\"?(https?://[^\"\s]+)", text)
            if not m:
                continue
            vid = _extract_vid_from_url(m.group(1))
            if vid:
                idx[vid] = ("## 转录" in text)
    _VIDEO_VID_INDEX[plat] = idx

def _md_is_complete(plat: str, url: str) -> bool:
    """视频平台: 该 vid 的 md 存在且有 ## 转录 才算完整; 否则视为空壳需重处理。
    非视频平台保持原 cache 行为(返回 True, 即尊重 cache 跳过)。"""
    if plat not in ("bilibili", "douyin"):
        return True
    vid = _extract_vid_from_url(url)
    if not vid:
        return True
    _ensure_vid_index(plat)
    return _VIDEO_VID_INDEX.get(plat, {}).get(vid, False)
from pipeline.run import process_url, process_search, detect_platform, _yymmdd_now, URL_PLATFORMS

TZ = timezone(timedelta(hours=8))

# 2026-07-16: 启用 faulthandler, SIGSEGV 时 dump 栈, 帮定位 watchlist hang 根因
# v2.2 教训: 必须保 file handle 引用 + signal handler (SIGTERM/SIGABRT) + atexit
import atexit
_STACK_FH = None
def _dump_on_exit():
    if _STACK_FH and not _STACK_FH.closed:
        try:
            _STACK_FH.flush()
            faulthandler.dump_traceback(file=_STACK_FH)
            _STACK_FH.flush()
        except Exception:
            pass
try:
    faulthandler.enable()
    (SKILL_DIR / "logs").mkdir(exist_ok=True, parents=True)
    _STACK_FH = open(str(SKILL_DIR / "logs" / f"stack_{os.getpid()}.dump"), "w")
    faulthandler.dump_traceback_later(90, repeat=True, file=_STACK_FH)
    atexit.register(_dump_on_exit)
    # SIGTERM/SIGABRT/SIGSEGV 触发时也 dump
    # v2.2.2 教训: os._exit(1) 不让 Python 走 cleanup, faulthandler dump 0 字节
    # 改用 sys.exit(128+sig) + 显式 flush, 让 dump_traceback 写入后再退出
    for _sig in (signal.SIGTERM, signal.SIGABRT):
        try:
            def _on_sig(s, f, _sig=_sig):
                _dump_on_exit()
                _msg = "\n⚠️ 收到信号 %d, dump 后退出\n" % _sig
                sys.stderr.write(_msg)
                sys.stderr.flush()
                sys.exit(128 + _sig)
            signal.signal(_sig, _on_sig)
        except Exception:
            pass
except Exception:
    pass
CLIP_CACHE = SKILL_DIR / "state" / "clip_cache.json"


# ───────────────────────── clip 模式 ─────────────────────────
def _load_clip_cache():
    if CLIP_CACHE.exists():
        try:
            return json.loads(CLIP_CACHE.read_text())
        except Exception:
            return {}
    return {}


def _save_clip_cache(c):
    CLIP_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CLIP_CACHE.write_text(json.dumps(c, ensure_ascii=False, indent=2))


def cmd_clip(dry_run=False):
    print("📋 剪藏模式: 读取 vault/01_my_notes/clip/*.md")
    try:
        text = read_clip_text()
    except Exception as e:
        print(f"❌ 读取 clip 队列失败: {e}")
        return
    urls = extract_urls(text)
    if not urls:
        print("  备忘录中暂无链接, 结束。")
        return
    print(f"  发现 {len(urls)} 个链接:")
    for u in urls:
        print(f"   - {canonical_key(u)}  {u[:70]}")

    cache = _load_clip_cache()
    processed = kept = 0
    for url in urls:
        plat = detect_platform(url)
        if plat not in URL_PLATFORMS:
            print(f"\n⏭️  不支持的平台(保留): {url[:70]}")
            kept += 1
            continue
        ck = "|".join(canonical_key(url))
        if ck in cache:
            print(f"\n♻️  已爬取(缓存命中), 删除备忘录行: {url[:70]}")
            if not dry_run:
                remove_url_from_note(url)
            processed += 1
            continue
        print(f"\n🚀 抓取 [{plat}]: {url[:70]}")
        if dry_run:
            processed += 1
            continue
        res = process_url(url, {"mode": "clip"})
        if res:
            cache[ck] = res[0]
            _save_clip_cache(cache)
            remove_url_from_note(url)
            processed += 1
        else:
            kept += 1
    print(f"\n{'[DRY-RUN] ' if dry_run else ''}完成: 处理 {processed} 条, 保留 {kept} 条")
    try:
        cleanup_tabs()
    except Exception:
        pass


def cmd_url(url, author=None, title=None):
    """单条 URL 剪藏 (run.sh url 入口).

    与 clip 模式同走 process_url(mode=clip)，但不读剪藏队列、不写缓存，
    适合手动验证/单帖补爬。
    """
    plat = detect_platform(url)
    if plat not in URL_PLATFORMS:
        print(f"⏭️  不支持的平台: {url[:70]}")
        return
    print(f"🚀 单条抓取 [{plat}]: {url[:80]}")
    res = process_url(url, {"mode": "clip"}, author=author, title_override=title)
    if res:
        print(f"✅ 完成: {res[0]}")
    else:
        print("⚠️ 抓取未产生结果(跳过/失败)")


# ───────────────────────── watchlist 模式 ─────────────────────────
def _extract_bili_mid(url):
    import re
    m = re.search(r"space\.bilibili\.com/(\d+)", url)
    if m:
        return m.group(1)
    m = re.search(r"bilibili\.com/\w+/(\d+)", url)
    if m:
        return m.group(1)
    return None


def _extract_douyin_secuid(url):
    import re
    from urllib.parse import urlparse, parse_qs
    # 1) query 形式: ?sec_uid=MS4w...
    q = parse_qs(urlparse(url).query)
    if "sec_uid" in q:
        return q["sec_uid"][0]
    # 2) path 形式(watchlist 常用): /user/MS4wLjABAAAA...
    m = re.search(r"/user/([A-Za-z0-9_\-]+)", url)
    if m:
        return m.group(1)
    return None


def _extract_douyin_vid(url):
    """从 watchlist URL 中提取 vid 参数（如有）."""
    from urllib.parse import urlparse, parse_qs
    q = parse_qs(urlparse(url).query)
    return q.get("vid", [None])[0]


def _list_bili_videos(mid, limit, _hard_timeout=30):
    """2026-07-16 v2.2: 加 hard timeout, 某些 mid 上 HTTP API 会 hang 死整个跑批.
    用 threading + Event 模拟 asyncio.wait_for. timeout=30s."""
    import threading
    from bili_feed import _load_bili_cookie
    from wbi import BilibiliWbi
    # BilibiliWebCrawler 使用 config.yaml（含过期bili_ticket），已弃用
    # 正确路径：bili_feed._load_bili_cookie() → BilibiliWbi → credentials/ominicrawl/bilibili.txt
    import asyncio
    cookie = _load_bili_cookie()
    _result = {"data": None, "err": None}
    def _runner():
        try:
            async def _go():
                async with BilibiliWbi(cookie=cookie) as bw:
                    return await bw.fetch_user_post_videos(mid=str(mid), pn=1)
            _result["data"] = asyncio.run(_go())
        except Exception as e:
            _result["err"] = e
    _t = threading.Thread(target=_runner, daemon=True)
    _t.start()
    _t.join(timeout=_hard_timeout)
    if _t.is_alive():
        # daemon thread 不会真的被 kill (Python 限制), 但 join timeout 后返回,
        # 让上层 skip 这个博主, 避免阻塞跑批
        raise TimeoutError(f"bili list mid={mid} 超时 {_hard_timeout}s")
    if _result["err"]:
        raise _result["err"]
    data = _result["data"] or {}
    code = data.get("code")
    if code != 0:
        raise RuntimeError(
            f"bili list mid={mid} API 失败: code={code}, msg={data.get('message', '')}")
    vlist = (data.get("data", {}) or {}).get("list", {}) or {}
    # 2026-08-15: 7 天窗口过滤.
    # 背景: 博主"最新视频"列表会无差别返回历史内容, 加 7 天 cutoff 只抓最近一周新发布的.
    # 不依赖 limit (limit=10 已不足以剔除历史堆积: 单博主 100+ 条历史视频时前 10 全是旧的).
    import time as _t
    _cutoff = int(_t.time()) - 7 * 86400
    _raw_vlist = vlist.get("vlist", [])
    _before = len(_raw_vlist)
    _filtered = [v for v in _raw_vlist if v.get("created", 0) >= _cutoff]
    _skipped = _before - len(_filtered)
    if _skipped:
        print(f"  ⏳ [bili] 7天窗口过滤: 跳过 {_skipped} 条历史视频 (mid={mid})", flush=True)
    vlist = _filtered[:limit]
    return [f"https://www.bilibili.com/video/{v['bvid']}" for v in vlist if v.get("bvid")]


def _select_douyin_videos(aweme_list, limit):
    """排除置顶作品后，按接口原顺序取 limit 条。返回 (items, pinned_count)。"""
    items = list(aweme_list or [])
    normal = [item for item in items if not item.get("is_top")]
    return normal[:limit], len(items) - len(normal)


def _list_douyin_videos(sec_uid, limit):
    """列举博主最新非置顶视频 URL 列表。

    返回值结构: {status, urls, msg, fetched_count, pinned_count}。
    status ∈ {ok, empty, error}；error 不应写入去重缓存。
    """
    import sys as _sys
    from pathlib import Path as _P
    _skill = _P(__file__).resolve().parent
    if str(_skill / "lib" / "douyin_api") not in _sys.path:
        _sys.path.insert(0, str(_skill / "lib" / "douyin_api"))
    import asyncio
    from crawlers.douyin.web.web_crawler import DouyinWebCrawler

    # 多取一些，避免 3 条置顶占掉目标的 10 条普通作品。
    fetch_count = max(30, limit + 10)
    crawler = DouyinWebCrawler()
    # 2026-08-13 fix: 抖音反爬限流(403 / aweme_list=None)会静默漏掉新视频。
    # 限流是短时窗口, 退避后重试通常能拿回新鲜列表, 不再直接 error→跳过。
    _backoff = (20, 40, 80)
    _max_retry = 3
    _last_err = ""
    result = None
    aweme_list = None
    for _att in range(1, _max_retry + 1):
        try:
            # 2026-08-22 fix: asyncio.run 本身无超时，改用 wait_for(30s) 防止 SSL 握手永久挂死
            try:
                import asyncio as _asyncio
                result = _asyncio.run(_asyncio.wait_for(
                    crawler.fetch_user_post_videos(sec_uid, max_cursor=0, count=fetch_count),
                    timeout=30))
            except _asyncio.TimeoutError:
                print(f"  ⏭ [dy] asyncio 超时(30s), 跳过该博主")
                return {"status": "error", "urls": [], "msg": "asyncio timeout",
                        "fetched_count": 0, "pinned_count": 0}
        except Exception as e:
            _last_err = f"库直连异常: {type(e).__name__}: {e}"
            # 2026-08-22: 网络异常才重试，403/风控立即跳过不等重试
            if "403" in str(e) or "Forbidden" in str(e) or "rate limit" in str(e).lower():
                print(f"  ⏭ [dy] 403/风控({_att}次), 跳过不等重试")
                return {"status": "error", "urls": [], "msg": _last_err,
                        "fetched_count": 0, "pinned_count": 0}
            if _att < _max_retry:
                print(f"  ⏳ [dy] 限流/异常(第{_att}次), {_backoff[_att-1]}s 后重试…")
                time.sleep(_backoff[_att-1])
                continue
            return {"status": "error", "urls": [], "msg": _last_err,
                    "fetched_count": 0, "pinned_count": 0}
        if not isinstance(result, dict):
            # 2026-08-22: 非 dict 通常是 403 HTML 响应，立即跳过
            print(f"  ⏭ [dy] 非 dict 响应(第{_att}次), 跳过")
            return {"status": "error", "urls": [], "msg": f"非 dict: {type(result).__name__}",
                    "fetched_count": 0, "pinned_count": 0}
        aweme_list = result.get("aweme_list")
        # status_code=0 + aweme_list=None 是典型限流签名 → 退避重试
        if aweme_list is None:
            _sc = result.get("status_code")
            _last_err = f"aweme_list=None, status_code={_sc}(风控/Cookie 过期/限流)"
            if _att < _max_retry:
                print(f"  ⏳ [dy] 限流(status_code={_sc}, 第{_att}次), {_backoff[_att-1]}s 后重试…")
                time.sleep(_backoff[_att-1])
                continue
            return {"status": "error", "urls": [], "msg": _last_err,
                    "fetched_count": 0, "pinned_count": 0}
        break  # 成功拿到列表
    if aweme_list is None:
        return {"status": "error", "urls": [], "msg": _last_err or "未知限流",
                "fetched_count": 0, "pinned_count": 0}

    selected, pinned_count = _select_douyin_videos(aweme_list, limit)
    # 2026-08-15: 7 天窗口过滤 (与 B 站同步).
    import time as _t
    _cutoff = int(_t.time()) - 7 * 86400
    _before = len(selected)
    selected = [a for a in selected if a.get("create_time", 0) >= _cutoff]
    _skipped = _before - len(selected)
    if _skipped:
        print(f"  ⏳ [dy] 7天窗口过滤: 跳过 {_skipped} 条历史视频 (sec_uid={sec_uid[:20]}...)", flush=True)
    urls = [f"https://www.douyin.com/video/{a['aweme_id']}"
            for a in selected if a.get("aweme_id")]
    return {
        "status": "empty" if not urls else "ok",
        "urls": urls,
        "msg": "",
        "fetched_count": len(aweme_list),
        "pinned_count": pinned_count,
    }


# 已知恒失败的抖音博主: 接口始终返回 aweme_list=None(status_code=0, 与登录态/Cookie
# 无关, 历史多轮 7/14/dy_watchlist/本轮均失败——属博主自身 sec_uid/主页问题)。
# 跳过避免每轮报错干扰增量爬取。若博主恢复, 从本集合移除即可。
_DY_KNOWN_BAD = {"付总人脉小课堂"}


def cmd_watchlist(date=None, only_platforms=None, only_bloggers=None):
    """运行 watchlist；可按平台及博主名精确过滤。"""
    date = date or _yymmdd_now()
    only = set(only_platforms or [])
    bloggers = set(only_bloggers or [])
    only_label = f", only={sorted(only)}" if only else ""
    blogger_label = f", blogger={sorted(bloggers)}" if bloggers else ""
    print(f"📡 Watchlist 模式 (date={date}{only_label}{blogger_label})")
    # 2026-07-27: Bailian 配额检测已上移到 supervisor.preflight_check()，这里不再重复检查

    # 进度监控初始化
    # 2026-08-22 排序调整: 抖音/B站 易卡死(网络/上传VM阻塞), 改为最后跑; 小红书/搜索型平台先完成保底
    PHASE_NAMES = ["小红书", "Boss直聘", "京东", "贴吧", "抖音", "B站"]
    if _PROGRESS:
        tracker = init_tracker(PHASE_NAMES)

    try:
        md = get_watchlist_markdown()
    except Exception as e:
        print(f"❌ 读取本地 Watchlist 失败: {e}")
        return

    # ── 1) 全局 watchdog (搜索/博主/小红书共用) ──
    # 2026-07-16: watchlist hang 诊断 - 每次进 process_search/process_url 前记录时间戳,
    # 后台 watchdog 线程 30 分钟无新进展时自动 dump 栈到 logs/stack_<pid>.dump
    WATCHDOG_TIMEOUT = 7200  # 2h, 长音频 MLX 转录保护  # 2026-07-21: MLX转录长音频可达数十分钟  # finalize LLM 总结 + 批量慢调容易超 90s, 拉宽减少误报
    _progress_ts = [time.time()]
    def _watchdog():
        while True:
            time.sleep(15)
            gap = time.time() - _progress_ts[0]
            if gap > WATCHDOG_TIMEOUT:
                fpath = SKILL_DIR / "logs" / f"stack_{os.getpid()}_watchdog.dump"
                fpath.parent.mkdir(exist_ok=True, parents=True)
                with open(fpath, "w") as f:
                    faulthandler.dump_traceback(file=f)
                print(f"\n⚠️ [watchdog] {gap:.0f}s 无进展, dump 栈后 SIGTERM 进程组", flush=True)
                # 杀整个进程组（包括 opencli/mlx 等 subprocess），防止卡死
                try:
                    pass  # 禁用 killpg; launchd 会重启
                except (ProcessLookupError, PermissionError):
                    pass  # 禁用 watchdog 杀进程; 靠 launchd 重启
                break
    _wd = threading.Thread(target=_watchdog, daemon=True)
    _wd.start()

    # ── 缓存与 hot.md 迁移准备 (抖音/B站 的实际爬取已移到文件末尾最后执行) ──
    cache = cache_load()
    # 2026-07-21: 补充 hot.md 中的 BV，防止新 cache 丢失旧数据导致重复处理
    import re
    vault_root = os.path.expanduser(os.environ.get("VAULT", "/Users/tianwenliang/Documents/steven_vault"))
    # hot.md BV migration: 内联实现，不引用不存在的 publish_vault._migrate_legacy_hot
    for plat in ("douyin", "bilibili"):
        hot_path = os.path.join(vault_root, "subscription", f"{plat}-hot.md")
        if os.path.exists(hot_path):
            with open(hot_path) as f:
                bvs = re.findall(r"BV[0-9A-Za-z]{10}", f.read())
            if bvs:
                existing = set(cache.get(plat, []))
                new_bvs = [bv for bv in bvs if bv not in existing]
                if new_bvs:
                    cache.setdefault(plat, [])
                    # 去重追加
                    for bv in new_bvs:
                        if bv not in cache[plat]:
                            cache[plat].append(bv)
                    print(f"  📥 [{plat}] 从 hot.md 补充 {len(new_bvs)} 个 BV 到缓存", flush=True)
    def _stage_summary(plat_label: str, subdir: str, t0: float):
        """打印某平台阶段落盘汇总：统计本阶段(t0 起)新增的 .md 文件并逐条打印相对 vault 路径。

        目的：让监控方(人/supervisor)一眼看到该平台真实产出，避免误判——
        例：小红书落盘目录是 subscription/xiaohongshu/ (非 xhs)，若只看目录名易误读为 0 产出。
        2026-07-26 新增：跑批日志结构化记录「下载了什么文件」。"""
        d = os.path.join(vault_root, "subscription", subdir)
        if not os.path.isdir(d):
            print(f"  📊 [{plat_label}] 本阶段 0 新增 (无落盘目录)")
            sys.stdout.flush()
            return
        added = []
        for root, _, files in os.walk(d):
            for fn in files:
                if fn.endswith(".md") and fn != ".DS_Store":
                    fp = os.path.join(root, fn)
                    if os.path.getmtime(fp) >= t0:
                        added.append(fp)
        n = len(added)
        if n:
            print(f"  📊 [{plat_label}] 本阶段新增 {n} 篇 → subscription/{subdir}/")
            for fp in added[:5]:
                print(f"       💾 {os.path.relpath(fp, vault_root)}")
            if n > 5:
                print(f"       … 其余 {n - 5} 篇")
        else:
            print(f"  📊 [{plat_label}] 本阶段 0 新增 (无新内容/全已缓存/失败)")
        sys.stdout.flush()

    def _opencli_daemon(action: str):
        """启停 opencli daemon (Chrome 副 profile 桥接载体).

        2026-07-26: LinkedIn 已 disable，全员纯 API 方案，daemon 不再在爬取链路中拉起。
        目前仅在 `generic` 平台 fallback 或微信文章时可能用到（rare）。
        为保持代码完整性保留本函数。
        action: 'restart' (冷启/确保运行) | 'stop' (释放资源).
        """
        import subprocess
        try:
            subprocess.run(
                ["opencli", "daemon", action],
                env={**os.environ, "NO_PROXY": "1"},
                timeout=90, capture_output=True,
            )
            print(f"  [opencli] daemon {action} 完成", flush=True)
        except Exception as e:
            print(f"  ⚠️  opencli daemon {action} 失败: {e}", flush=True)

    # 2026-08-14 用户决策: limit=10 (折中)。
    # 背景: 原 limit=5 下博主单日发 >5 条时, 第6条起的当天视频会被挤出 top5 而漏抓;
    #       实测昨日(Aug-13)真实发布≈27个, limit=5 仅抓回8个, 其余靠 limit=30 补回。
    #       用户先要求保5, 后权衡改为10——兼顾"单日连发≤10条不漏当天"与避免历史堆积。
    # 同期已固化修复(与 limit 无关, 不受影响): 去重循环缩进 bug(2026-08-12 引入)、抖音限流重试退避、博主间 8s 延时。
    limit = 10
    # 2026-08-22 排序调整: 抖音/B站(易卡死) 改到最后跑; 顺序 小红书 → 搜索型 → 抖音/B站

    # ── 1) 小红书 (xiaohongshu): 调 xhs-cli API, 直接追加 vault hot.md (不用 notes/) ──
    if _PROGRESS:
        tracker.set_phase(0)  # 小红书 (排第一, 先保底)
        if not can_monitor("xiaohongshu"):
            print("  ⏭️  [xiaohongshu] monitor=false, 跳过 watchlist 监控")
        else:
            t0_xhs = time.time()
            try:
                from tools.xiaohongshu import crawl_batch as _xhs_batch
                _xhs_batch(date)
            except Exception as e:
                print(f"  ❌ xiaohongshu: {e}")
            _stage_summary("小红书", "xiaohongshu", t0_xhs)

    # 小红书爬完立即清理 tabs（xhs-crawl 内部也有 cleanup，这里双重保险）
    try:
        cleanup_tabs()
    except Exception:
        pass

    # ── 2) 搜索型平台 (boss/jd/tieba/linkedin): 三大博主平台后跑（次要） ──
    # 2026-07-22: 用户决策 — 抖音/B站/小红书优先, 搜索型滞后
    # 2026-07-26: linkedin 已 disable（全员纯 API 方案）
    # 2026-07-26: linkedin 已 disable（全员纯 API 方案）
    #   boss/jd/tieba 均走各自 HTTP API，不依赖 opencli
    #   xhs 走独立工具，douyin/bilibili 走 API + ASR，均不依赖 opencli
    SEARCH_PHASE_START = 1  # 2026-08-22: 小红书占 phase0, 搜索从 phase1 起
    search_platforms = ["boss", "jd", "tieba"]
    for p_idx, plat in enumerate(search_platforms):
        _progress_ts[0] = time.time()
        if only and plat not in only:
            print(f"  ⏭️  [{plat}] 被 --platform 过滤, 跳过")
            continue
        if _PROGRESS:
            tracker.set_phase(SEARCH_PHASE_START + p_idx)
        try:
            import resource  # 内存监控
            rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            print(f"  [diag] pid={os.getpid()} rss={rss_mb:.0f}MB, 进入 [{plat}]", flush=True)
            t0_search = time.time()
            process_search(plat, date)
            _progress_ts[0] = time.time()
            if plat != "boss":  # boss 已 disable, 无落盘目录
                _stage_summary(plat, plat, t0_search)
        except Exception as e:
            print(f"  ❌ {plat} 搜索异常: {e}")

    try:
        cleanup_tabs()
    except Exception:
        pass


    # ── 3) 抖音/B站 (2026-08-22 移到最后): 易卡死(网络/上传VM阻塞), 排最后跑, 不连坐其它平台 ──
    for plat in ("douyin", "bilibili"):
        if only and plat not in only:
            print(f"  ⏭️  [{plat}] 被 --platform 过滤, 跳过")
            continue
        rows = parse_rows(md, plat)
        if bloggers:
            rows = [(url, name, ocr_flag) for url, name, ocr_flag in rows if name in bloggers]
        if not rows:
            if bloggers:
                print(f"  ⏭️  [{plat}] 未匹配指定博主: {sorted(bloggers)}")
            continue
        phase_idx = 4 if plat == "douyin" else 5  # 2026-08-22: 抖音/B站移到最后(phase4/5)
        tracker.set_phase(phase_idx, len(rows)) if _PROGRESS else None
        print(f"\n📺 {plat}: {len(rows)} 个博主")
        t0_plat = time.time()
        if plat == "douyin":
            cmd_watchlist._dy_idx = 0  # 2026-08-13 fix (①): 博主间延时计数器复位
        for url, name, ocr_flag in rows:
            try:
                if plat == "bilibili":
                    mid = _extract_bili_mid(url)
                    if not mid:
                        # 可能直接是视频 BV 链接 → 直接处理
                        if "bilibili.com/video/" in url:
                            process_url(url, {"mode": "watchlist", "date": date})
                        else:
                            print(f"  ⏭️  {name}: 无法解析 bilibili mid: {url[:60]}")
                        continue
                    vids = _list_bili_videos(mid, limit)
                else:
                    vid = _extract_douyin_vid(url)
                    suid = _extract_douyin_secuid(url)
                    if vid:
                        # vid= 指向特定视频，优先直接处理这条
                        video_url = f"https://www.douyin.com/video/{vid}"
                        process_url(video_url, {"mode": "watchlist", "date": date})
                        _progress_ts[0] = time.time()
                        if _PROGRESS and tracker:
                            tracker.inc_item()
                    if not suid:
                        if "douyin.com/video/" in url:
                            process_url(url, {"mode": "watchlist", "date": date})
                        else:
                            print(f"  ⏭️  {name}: 无法解析 douyin sec_uid: {url[:60]}")
                        continue
                    if name in _DY_KNOWN_BAD:
                        print(f"  ⏭️  {name}: 已知失效博主(接口恒返回空, 与登录无关), 跳过")
                        continue
                    # 2026-08-13 fix (①): 博主间加延时，错开抖音反爬限流窗口
                    # 连续 14 博主快速请求必触发限流 → 退避式间隔分散命中
                    _dy_idx = getattr(cmd_watchlist, "_dy_idx", 0)
                    if _dy_idx > 0:
                        print(f"  ⏸️  [dy] 博主间延时 8s 错开限流 (第{_dy_idx}位)…")
                        time.sleep(8)
                    vids = _list_douyin_videos(suid, limit)
                    cmd_watchlist._dy_idx = _dy_idx + 1
            except Exception as e:
                msg = str(e)[:120]
                if isinstance(e, TimeoutError):
                    print(f"  ⏭️  {name}: 视频列表超时, skip")
                else:
                    print(f"  ❌ {name}: 展开视频失败: {msg}")
                continue
            # 抖音 _list_douyin_videos 返回 dict 状态对象; 其他平台 (bili) 仍返回 list
            if isinstance(vids, dict):
                _plat_label = "dy"
                if vids["status"] == "error":
                    print(f"  ❌ [{_plat_label}] {name}: {vids['msg']}")
                    continue
                if vids["status"] == "empty":
                    print(f"  ⏭️  [{_plat_label}] {name}: 本批无新视频(aweme_list=[])")
                    continue
                if vids.get("pinned_count"):
                    print(f"  ℹ️  {name}: 获取 {vids.get('fetched_count', 0)} 条，"
                          f"过滤 {vids['pinned_count']} 条置顶，处理 {len(vids['urls'])} 条")
                vids_list = vids["urls"]
            else:
                vids_list = vids
            if not vids_list:
                print(f"  ⏭️  {name}: 无新视频")
                continue
            # 进度监控：博主维度
            if _PROGRESS and tracker:
                tracker.set_blogger(name, len(vids_list))
            # 去重: 用视频 id 缓存
            seen = set(cache.get(plat, []))
            for v in vids_list:
                vid = canonical_key(v)[1]
                if vid in seen:
                    # 2026-08-12 fix: 空壳(有 frontmatter 无 ## 转录)不视为已处理, 重抓补转录
                    if _md_is_complete(plat, v):
                        print(f"  ⏭️  [{plat}] {name}: 已缓存({vid[:12]}), 跳过")
                        continue
                    # 缓存命中但内容不完整 → 清 cache 记录并重处理
                    seen.discard(vid)
                    print(f"  🔁 [{plat}] {name}: 缓存命中但空壳({vid[:12]}), 重处理")
                else:
                    # 未缓存 → 真实新视频, 下载/转录并写入缓存
                    print(f"  🆕 [{plat}] {name}: 新视频 {vid[:12]} 处理中")
                res = process_url(v, {"mode": "watchlist", "date": date})
                # 2026-07-21: 每个视频处理完更新 watchdog，防止长音频 MLX 转录超 240s
                _progress_ts[0] = time.time()
                if _PROGRESS and tracker:
                    tracker.inc_item()
                if res:
                    seen.add(vid)
            cache[plat] = list(seen)[-500:]
            cache_save(cache)
            _stage_summary(plat, plat, t0_plat)
    # B站/抖音 爬完立即清理 tabs
    try:
        cleanup_tabs()
    except Exception:
        pass

    print("\n✅ Watchlist 抓取完成 (直接落 vault hot.md)")
    # 全平台爬取完成 → 关 opencli 残留 tabs + 关闭独立 Chrome 窗口
    # 2026-07-17 修复: 不再走 AppleScript 反向匹配窗口名 (会误关用户主 Chrome),
    # 改为按 UDD 精准 pkill (cleanup_isolated_chrome_window)
    try:
        cleanup_tabs()
    except Exception:
        pass
    cleanup_isolated_chrome_window()

    # 生成每日汇总（传入 crawl 实际日期，避免跨天跑批时用错日期）
    import subprocess
    try:
        # 2026-07-26 fix: 去掉多余的 .parent (SKILL_DIR 已是 crawl/ 根)
        today_py = SKILL_DIR / "common-today" / "gen_today.py"
        # date 可能是 8位(YYYYMMDD) / 6位(YYMMDD) / 已是 YYYY-MM-DD
        if len(date) == 8 and date.isdigit():
            yyyy_mm_dd = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
        elif len(date) == 6 and date.isdigit():
            yyyy_mm_dd = f"20{date[:2]}-{date[2:4]}-{date[4:6]}"
        else:
            yyyy_mm_dd = date
        r = subprocess.run(
            [sys.executable, str(today_py), yyyy_mm_dd],
            capture_output=True, text=True
        )
        if r.stdout.strip():
            print(r.stdout.strip())
        if r.returncode != 0 or r.stderr.strip():
            print(f"[common-today] 警告: 退出码={r.returncode}, stderr={r.stderr.strip()[:300]}")
    except Exception as e:
        print(f"[common-today] 生成失败: {e}")

    if _PROGRESS and tracker:
        tracker.summary()
    print("\n✅ Watchlist 全流程完成")



def main():
    ap = argparse.ArgumentParser(prog="crawl", description="ominicrawl 统一入口")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("clip", help="读剪藏队列 (vault/01_my_notes/clip/*.md → vault/00_inbox/)").add_argument("--dry-run", action="store_true")

    p_w = sub.add_parser("watchlist", help="读本地 Watchlist 全平台 (vault 根 watchlist.md)")
    p_w.add_argument("--date")
    p_w.add_argument("--platform", action="append",
                     help="只跑指定平台(可多次)。支持: boss/jd/linkedin/tieba/bilibili/douyin/xiaohongshu")
    p_w.add_argument("--blogger", action="append",
                     help="只跑指定博主名(精确匹配，可多次；需配合 --platform douyin/bilibili)")

    p_set = sub.add_parser("set-tool", help="切换平台工具")
    p_set.add_argument("platform")
    p_set.add_argument("tool")

    sub.add_parser("tools", help="打印平台→工具映射")

    p_u = sub.add_parser("url", help="单条 URL 剪藏 (run.sh url 入口)")
    p_u.add_argument("url", help="要爬取的帖子 URL")
    p_u.add_argument("--author", default=None, help="可选: 指定作者名")
    p_u.add_argument("--title", default=None, help="可选: 覆盖标题")

    args = ap.parse_args()
    if args.cmd == "clip":
        cmd_clip(args.dry_run)
    elif args.cmd == "watchlist":
        if args.blogger:
            if not args.platform or any(p not in {"douyin", "bilibili"} for p in args.platform):
                ap.error("--blogger 需配合 --platform douyin 或 --platform bilibili")
        cmd_watchlist(args.date, args.platform, args.blogger)
    elif args.cmd == "set-tool":
        set_tool(args.platform, args.tool)
        print(f"✅ {args.platform} → {args.tool}")
    elif args.cmd == "tools":
        print(show_tools())
    elif args.cmd == "url":
        cmd_url(args.url, args.author, args.title)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
