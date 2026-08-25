import sys, os
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

#!/usr/bin/env python3
"""
fetch_dy_v2.py - 抖音博主视频抓取 (v2.1, DouyinWebCrawler API + 本地转录)
  - 走 DouyinWebCrawler API (Cookie + a_bogus 签名)
  - USE_VM=true: 仅落元数据, 转录走 VM daemon
  - USE_VM=false: Mac 本地转录 (Groq → faster-whisper), ffmpeg 直接从视频URL流式抽音频
  - 60s 硬超时保护
"""

import sys as _sys
from pathlib import Path as _P
_SKILL_ROOT = str(_P(__file__).resolve().parent.parent)
if _SKILL_ROOT not in _sys.path:
    _sys.path.insert(0, _SKILL_ROOT)

import os, sys, re, json, time, asyncio, signal, subprocess, tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

# 添加 lib/douyin_api + scripts 到 Python path
_SKILL_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_SKILL_DIR / "lib" / "douyin_api"))
sys.path.insert(0, str(_SKILL_DIR / "scripts"))
from common.fetch_log import append_fetch_log as _append_log, _detect_share
from crawlers.douyin.web.web_crawler import DouyinWebCrawler
from common.transcribe import transcribe, apply_transcript, load_config, USE_VM as _USE_VM_CONFIG
import shutil as _shutilCrawl
from common.paths import notes_dir, cache_file
from common.util import (
    sanitize,
    to_yymmdd,
    yml_escape,
    dedup,
    cache_load,
    cache_save,
    fld,
)

TZ = timezone(timedelta(hours=8))
PLATFORM = "douyin"
CATEGORY = "douyin"
SHARE = _detect_share()
CACHE_FILE = cache_file()
LLM_SCR = _SKILL_DIR / "common" / "llm.py"

# 2026-07-30 v2: per-item event 写到 events.jsonl (CRAWL_RUN_TAG 由 supervisor 注入)
_RUN_TAG = os.environ.get("CRAWL_RUN_TAG", "")

def _emit_event(event: str, **kwargs):
    """往 events.jsonl 写一条结构化事件 (CRAWL_RUN_TAG 为空时 no-op)."""
    if not _RUN_TAG:
        return
    try:
        from common_supervisor import run_meta
        run_meta.append_event(_RUN_TAG, event, platform=PLATFORM, **kwargs)
    except Exception:
        pass

def _get_use_vm():
    env_vm = os.environ.get("USE_VM", "")
    if env_vm.lower() in ("true", "1", "yes"):
        return True
    if env_vm.lower() in ("false", "0", "no"):
        return False
    return _USE_VM_CONFIG

def _get_limit():
    """读取 LIMIT: 环境变量 OVERRIDE_LIMIT > config.yaml > 默认 10"""
    env = os.environ.get("OVERRIDE_LIMIT", "")
    if env.isdigit():
        return int(env)
    try:
        cfg = load_config()
        return int(cfg.get("LIMIT", 10))
    except Exception:
        return 10

USE_VM = _get_use_vm()
LIMIT = _get_limit()

class TimeoutError(Exception): pass

def timeout_handler(signum, frame):
    raise TimeoutError("60s 硬超时，跳过")

def log(m): print(f"  {m}", flush=True)

def _scan_pending_dy():
    """修 #18 (2026-08-01): 启动时扫描 PENDING_AUDIO_DIR 残留 wav, 加入本批 deferred.
    不删 wav, 只读 metadata + wav_path."""
    items = []
    pdir = Path(__file__).resolve().parents[2] / "state" / "pending_audio" / PLATFORM  # crawl/state/pending_audio/douyin
    if not pdir.exists():
        return items
    for wav in pdir.glob("*.wav"):
        aweme_id = wav.stem
        items.append({
            "wav_path": str(wav),
            "source": "",
            "headers": {},
            "meta": {"aweme_id": aweme_id, "blogger": "", "video_url": "", "md_path": ""},
        })
    return items


def _retry_deferred(deferred):
    """修 #1 + #18 (2026-07-30 / 2026-08-01): 本批次结束前 retry 所有 deferred 项.
    修 #1: 极简版 transcribe() raise-only, batch 末尾 retry.
    修 #18: 优先用 wav_path (PENDING_AUDIO_DIR) 直接喂 wav, 没有 wav_path 才流式重抽.
    返回: (retry_ok, retry_fail)
    """
    import os as _os_retry
    retry_ok = []
    retry_fail = []
    for item in deferred:
        meta = item.get("meta", {})
        aweme_id = meta.get("aweme_id", "unknown")
        wav = item.get("wav_path")
        try:
            if wav and _os_retry.path.exists(wav):
                # 修 #18: 持久化 wav 直接喂, 跳过流式抽音频
                text, src_tag = transcribe(wav)
            elif item.get("source"):
                text, src_tag = transcribe(item["source"], headers=item.get("headers"))
            else:
                retry_fail.append({"aweme_id": aweme_id, "error": "no wav_path or source"})
                continue
            if text:
                retry_ok.append({
                    "aweme_id": aweme_id,
                    "transcript": text,
                    "source": src_tag,
                    "md_path": meta.get("md_path", ""),
                })
            else:
                retry_fail.append({"aweme_id": aweme_id, "error": "transcribe() returned empty"})
        except Exception as e:
            retry_fail.append({"aweme_id": aweme_id, "error": str(e)})
    return retry_ok, retry_fail


def fetch_via_api(sec_uid):
    """走 DouyinWebCrawler API (a_bogus 签名, Cookie 从 config.yaml 读取)"""
    try:
        crawler = DouyinWebCrawler()
        result = asyncio.run(crawler.fetch_user_post_videos(sec_uid, max_cursor=0, count=LIMIT))
        if not isinstance(result, dict):
            log(f"API 返回非 dict: {type(result).__name__}")
            return None
        aweme_list = result.get("aweme_list")
        if aweme_list is None:
            # 检查是否是 Cookie 过期或风控
            status = result.get("status_code", "N/A")
            log(f"API 无 aweme_list, status_code={status} (可能 Cookie 过期)")
            return None
        if not aweme_list:
            log("aweme_list 为空")
            return []
        log(f"API 返回 {len(aweme_list)} 条")
        return aweme_list[:LIMIT]
    except Exception as e:
        log(f"API err: {type(e).__name__}: {e}")
        return None

def main():
    if len(sys.argv) < 3:
        print("usage: fetch_dy_v2.py <sec_uid> <name> [out_dir]", file=sys.stderr)
        sys.exit(1)

    sec_uid = sys.argv[1]
    blogger = sys.argv[2]
    out_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else notes_dir() / PLATFORM / blogger
    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"博主 [{blogger}] {sec_uid[:20]}... USE_VM={USE_VM}")

    # 注册硬超时
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(60)

    # 修 #1 #2 (2026-07-30): 失败 wav 持久化目录 + 本批次 deferred queue
    PENDING_AUDIO_DIR = Path(__file__).resolve().parents[2] / "state" / "pending_audio" / PLATFORM  # crawl/state/pending_audio/douyin
    PENDING_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    deferred = []  # 本批次失败项, 主循环结束前 retry
    # 修 #18 (2026-08-01): 启动 scan PENDING_AUDIO_DIR 残留 wav, 加入本批 deferred (跨 batch retry)
    _pending_dy = _scan_pending_dy()
    if _pending_dy:
        deferred.extend(_pending_dy)
        log(f"  📂 PENDING_AUDIO_DIR: {len(_pending_dy)} 个残留 wav 跨 batch retry")

    awemes = fetch_via_api(sec_uid)

    signal.alarm(0)  # 取消超时

    if awemes is None:
        log("API 返回 None，超时或出错，直接跳过")
        print(f"BLOGGER_OK  0 条 ok (api fail)")
        return

    if not awemes:
        log("视频列表为空（可能无 cookie / 风控 / 视频已删）")
        print(f"BLOGGER_OK  0 条 ok (empty)")
        return

    log(f"视频列表: {len(awemes)} 条")
    cache = cache_load().get(PLATFORM, [])
    cache_set = set(cache)

    ok_count, skip_count = 0, 0
    _total = min(len(awemes), LIMIT)
    for _i, aweme in enumerate(awemes[:LIMIT], 1):
        aweme_id = aweme.get("aweme_id", "")
        if not aweme_id: continue
        if aweme_id in cache_set:
            log(f"[{aweme_id[:12]}] cached, 跳过")
            skip_count += 1; continue
        # 2026-07-30 v2: per-item 进度行 (ActionMonitor 解析 + 用户肉眼可见)
        log(f"  [item {_i}/{_total}] douyin @{blogger} aweme={aweme_id[:12]} phase=start")
        _emit_event("item_start", item_idx=_i, item_total=_total, blogger=blogger, aweme_id=aweme_id)
        _item_t0 = time.time()

        desc = fld(aweme.get("desc","")) or "(无标题)"
        publish_ms = aweme.get("create_time", 0)
        publish_iso = datetime.fromtimestamp(publish_ms, TZ).strftime("%Y-%m-%dT%H:%M:%S") if publish_ms else datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S")
        stats = aweme.get("statistics", {}) or {}
        likes = stats.get("digg_count", 0) or 0
        comments = stats.get("comment_count", 0) or 0
        favorites = stats.get("collect_count", 0) or 0
        shares = stats.get("share_count", 0) or 0

        # 提取视频播放URL (无水印)
        video_url = ""
        try:
            vl = aweme.get("video",{}) or {}
            video_url = (vl.get("play_addr",{}) or {}).get("url_list", [None])[0] or \
                         (vl.get("download_addr",{}) or {}).get("url_list", [None])[0] or ""
        except: pass
        duration_ms = 0
        try: duration_ms = (aweme.get("video",{}) or {}).get("duration", 0) or 0
        except: pass

        yymmdd = to_yymmdd(publish_ms)
        safe = f"{yymmdd}-{sanitize(desc)}"
        out_md = dedup(out_dir / f"{safe}.md")
        source_url = f"https://www.douyin.com/video/{aweme_id}"

        # ── 本地转录 (USE_VM=false) ──
        transcript = ""
        transcribe_source = ""
        if not USE_VM and video_url:
            log(f"  [{aweme_id[:12]}] 流式抽音频+转录...")
            # ffmpeg 直接从视频 URL 抽取音频流 (不下 mp4)
            dy_headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer": "https://www.douyin.com/",
            }
            # 2026-07-30 极简模式: transcribe() 失败 raise RuntimeError, 单条 catch 不杀整批
            # 修 #18 (2026-08-01): caller 自己创建 tempdir, 失败时 move wav 到 PENDING_AUDIO_DIR
            #   跨 batch retry 直接喂 wav, 跳过流式抽音频 + 绕过 524 timeout
            _self_tmp = tempfile.mkdtemp(prefix=f"dy_{aweme_id}_")
            try:
                transcript, transcribe_source = transcribe(
                    video_url, headers=dy_headers,
                    tmp_dir=_self_tmp,
                )
                # 修 #18: 转录成功 → 清 PENDING_AUDIO_DIR 里同 aweme_id 的 wav (上次失败留下的)
                _pending_wav = PENDING_AUDIO_DIR / f"{aweme_id}.wav"
                if _pending_wav.exists():
                    _pending_wav.unlink()
            except RuntimeError as e:
                # Groq 失败 → 醒目日志, 不影响其它视频 (用户原话: 'groq 走不通就报错退出, 但这里是单条失败不应杀整批')
                log(f"  ⚠️ [{aweme_id[:12]}] [ASR.FATAL] Groq 转录失败, 跳过 (batch 其它视频继续): {e}")
                transcript, transcribe_source = "", "fatal"
                # 修 #16 + #18 (2026-08-01): 极简版 transcribe() raise-only, caller 手动入队.
                # 修 #18: 失败时 move wav 到 PENDING_AUDIO_DIR (跨 batch retry 用)
                _wav_p = os.path.join(_self_tmp, "audio.wav")
                _wav_persisted = None
                if os.path.exists(_wav_p):
                    target = PENDING_AUDIO_DIR / f"{aweme_id}.wav"
                    try:
                        _shutilCrawl.move(_wav_p, target)
                        _wav_persisted = str(target)
                        log(f"  [persist] wav -> PENDING_AUDIO_DIR/{aweme_id}.wav")
                    except Exception as mv_e:
                        log(f"  ⚠️ wav 持久化失败: {mv_e}")
                if deferred is not None:
                    deferred.append({
                        "wav_path": _wav_persisted,
                        "source": video_url,
                        "headers": dy_headers,
                        "meta": {"aweme_id": aweme_id, "blogger": blogger,
                                   "video_url": video_url, "md_path": str(out_md)},
                    })
            finally:
                # 清理 caller 自己的 tempdir (wav 已被 move, 这里只清空目录)
                try:
                    _shutilCrawl.rmtree(_self_tmp, ignore_errors=True)
                except Exception:
                    pass
            if transcript:
                log(f"  [{aweme_id[:12]}] 转录完成: {transcribe_source}, {len(transcript)} 字")
            elif transcribe_source == "fatal":
                # 已打印 [ASR.FATAL], 不重复
                pass
            else:
                log(f"  [{aweme_id[:12]}] 转录失败/跳过, 已入 deferred queue")

        # ── 写 MD ──
        fm = ["---"]
        fm.append(f"title: {yml_escape(desc)}")
        fm.append(f"publish_time: {publish_iso}")
        fm.append(f"category: {CATEGORY}")
        fm.append(f"source_url: {source_url}")
        fm.append(f"uid: {aweme_id}")
        fm.append(f"author: {yml_escape(blogger)}")
        if duration_ms: fm.append(f"duration: {duration_ms//1000}")
        if transcript:
            fm.append(f"transcript_source: {transcribe_source}")
            fm.append("transcript_available: true")
            fm.append("transcript_pending: false")
        else:
            fm.append('transcript_available: false')
            fm.append("transcript_pending: true")
        if likes: fm.append(f"likes: {likes}")
        if comments: fm.append(f"comments: {comments}")
        if favorites: fm.append(f"favorites: {favorites}")
        if shares: fm.append(f"shares: {shares}")
        fm.append('source: "douyin_api"')
        fm.append(f"created: {datetime.now(TZ).strftime('%Y-%m-%dT%H:%M:%S')}")
        fm.append(f"aweme_id: {aweme_id}")
        if USE_VM:
            fm.append('status: ["transcribing","summarizing","abstracting"]')
        else:
            fm.append('status: ["summarizing","abstracting"]')
        fm.append("---")
        fm.append("")
        fm.append(f"## {desc}")
        if transcript:
            fm.append("")
            fm.append(f"## 转录 (来源: {transcribe_source})")
            fm.append("")
            fm.append(transcript)
        fm_text = "\n".join(fm)

        out_md.write_text(fm_text, encoding="utf-8")
        log(f"  → {out_md.name}")

        # 转录成功后立刻总结+速读
        if transcript and not USE_VM:
            log(f"  总结中... ")
            try:
                llm_r = subprocess.run(
                    [sys.executable, str(LLM_SCR), str(out_md)],
                    capture_output=True, text=True, timeout=180
                )
                if llm_r.returncode == 0:
                    log("✅")
                else:
                    log(f"(稍后: {llm_r.stderr.strip()[:60]})")
            except subprocess.TimeoutExpired:
                log("(超时, batch 兜底)")
            except Exception as e:
                log(f"(异常: {e})")

        _append_log(platform="douyin", uid=aweme_id, md_abs_path=str(out_md), blogger=blogger, title=desc)

        # 修 #1 (2026-07-30): 转录失败不入 cache, 否则永远跳过
        _item_dur = time.time() - _item_t0
        if transcript:
            cache.append(aweme_id)
            ok_count += 1
            log(f"  [item {_i}/{_total}] douyin @{blogger} aweme={aweme_id[:12]} phase=done outcome=success duration={_item_dur:.1f}s")
            _emit_event("item_done", item_idx=_i, item_total=_total, blogger=blogger,
                        aweme_id=aweme_id, outcome="success",
                        asr_source=transcribe_source, duration_sec=round(_item_dur, 1))
        else:
            log(f"  [{aweme_id[:12]}] 跳过 cache.append (转录失败, 待 batch retry)")
            log(f"  [item {_i}/{_total}] douyin @{blogger} aweme={aweme_id[:12]} phase=done outcome=asr_failed duration={_item_dur:.1f}s")
            _emit_event("item_done", item_idx=_i, item_total=_total, blogger=blogger,
                        aweme_id=aweme_id, outcome="asr_failed",
                        duration_sec=round(_item_dur, 1))
            skip_count += 1
        time.sleep(2)

    # 修 #1: 本批次结束前 retry deferred (失败 wav 已在 state/pending_audio/)
    if deferred:
        log(f"🔁 batch retry deferred: {len(deferred)} 条")
        retry_ok, retry_fail = _retry_deferred(deferred)
        for item in retry_ok:
            if item.get("md_path") and item.get("transcript"):
                apply_transcript(item["md_path"], item["transcript"], source=item.get("source", ""))
                if item.get("aweme_id"):
                    cache.append(item["aweme_id"])
                    ok_count += 1
        for item in retry_fail:
            log(f"  [{item['aweme_id'][:12]}] 重试仍失败: {item['error'][:80]}")

    cache_save({**cache_load(), PLATFORM: cache[-500:]})
    print(f"BLOGGER_OK  {ok_count} 条 ok, {skip_count} 条 skip, deferred_retry {len(deferred)}")

if __name__ == "__main__":
    try:
        main()
    except TimeoutError as e:
        print(f"BLOGGER_OK  0 条 ok (timeout)")
    except KeyboardInterrupt:
        print("中断")
