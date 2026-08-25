#!/usr/bin/env python3
"""bili_feed — B站辅助函数（BiliBili WBI 签名 + 通用工具）
供 bilibili/crawl.py 调用
"""

import sys as _sys
from pathlib import Path as _P
_SKILL_ROOT = str(_P(__file__).resolve().parent.parent)
if _SKILL_ROOT not in _sys.path:
    _sys.path.insert(0, _SKILL_ROOT)

import json, os, re, subprocess, sys, time, urllib.request
from datetime import datetime
from pathlib import Path

SKILL_DIR = Path(__file__).parent
CREDS_DIR = Path.home() / '.agents' / 'credentials' / 'ominicrawl'
sys.path.insert(0, str(SKILL_DIR))
from common.paths import notes_dir, cache_file
from common.util import dedup, yml_escape
VAULT_DEFAULT = notes_dir()  # 仅兜底默认值, 实际输出由 fetch_v3 用 notes_dir()

def _detect_vault():
    """探测笔记根目录(脱离 steven_vault)"""
    try:
        return notes_dir()
    except Exception:
        return VAULT_DEFAULT

def _load_bili_cookie():
    """加载 B站 cookie"""
    cred = CREDS_DIR / 'bilibili.txt'
    if cred.exists():
        return cred.read_text(encoding='utf-8').strip()
    return ''

def _parse_hdrs(headers):
    d = {}
    if not headers:
        return d
    for line in headers.split('\n'):
        line = line.strip()
        if line and ':' in line:
            k, v = line.split(':', 1)
            d[k.strip()] = v.strip()
    return d

def _audio_download_with_retry(audio_url, hdr, dl, timeout=180, max_retries=3):
    """urllib 下载音频流, 带超时+重试+剥代理。

    修复 2026-07-21:
    - timeout 120s → 180s（B站 mcdn 偶发 SSL read 慢, 旧 120s 不够）
    - retry 3 次（首次失败间隔 2/4s 后重试）
    - ProxyHandler({}) 剥代理, 避免 Clash 误伤国内 CDN

    Returns: bool
    """
    if not hdr.get('User-Agent'):
        hdr['User-Agent'] = (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
        )
    # 2026-07-26: 恢复剥代理直连 — B站 upos/mcdn 经 Clash 代理走慢路由(~30KB/s),
    # 直连国内CDN 恢复正常 MB/s。仅 B站音频下载用; douyin API/媒体仍走代理。
    _opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    # 2026-08-22 fix: SSL 读超时保护，防止 ssl.read() 永久阻塞
    import socket
    socket.setdefaulttimeout(timeout)
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(audio_url, headers=hdr)
            with _opener.open(req, timeout=timeout) as resp, open(dl, 'wb') as f:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
            if os.path.exists(dl) and os.path.getsize(dl) > 0:
                return True
        except Exception as e:
            print(f"    WARN audio dl attempt {attempt}/{max_retries} failed: {e}", flush=True)
            if os.path.exists(dl):
                try: os.remove(dl)
                except Exception: pass
            if attempt < max_retries:
                time.sleep(2 * attempt)
    return False


def audio_to_wav(audio_url, out_wav, headers=''):
    """下载音频/视频流并转码为 wav。

    注意：B站 upos CDN 对 ffmpeg 内置 HTTP 客户端返回 403（hotlink 保护），
    但用 Python urllib / curl 直连可正常下载。故改为先 urllib 下载到本地，
    再 ffmpeg 仅做本地转码——对 mcdn / upos 均通用。

    2026-07-21: 增加 retry 3 次 + timeout 180s + 剥代理.
    """
    hdr = _parse_hdrs(headers)
    dl = out_wav + '.src'
    if not _audio_download_with_retry(audio_url, hdr, dl, timeout=180, max_retries=3):
        return False
    # 本地转码
    cmd = ['ffmpeg', '-y', '-i', dl, '-ar', '16000', '-ac', '1',
           '-loglevel', 'error', out_wav]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=180)
    except subprocess.TimeoutExpired:
        print(f"    WARN ffmpeg 转码超时 (180s): {dl}", flush=True)
        if os.path.exists(dl):
            try: os.remove(dl)
            except Exception: pass
        return False
    try:
        os.remove(dl)
    except Exception:
        pass
    return r.returncode == 0 and os.path.exists(out_wav)

def to_yymmdd(val):
    """各种时间格式 → yymmdd
    注意: B站 created 字段是「秒」级时间戳, 故此处直接按秒解析(不 /1000)。
    与 common.util.to_yymmdd(按毫秒) 语义不同, 勿混用。"""
    if not val: return datetime.now().strftime('%y%m%d')
    try:
        if isinstance(val, (int, float)):
            return datetime.fromtimestamp(val).strftime('%y%m%d')
        val = str(val).strip()
        for fmt in ['%Y-%m-%dT%H:%M:%S','%Y-%m-%d %H:%M:%S','%Y-%m-%d']:
            try:
                return datetime.strptime(val[:19], fmt).strftime('%y%m%d')
            except: pass
        return datetime.now().strftime('%y%m%d')
    except:
        return datetime.now().strftime('%y%mdd')

def log(m): print(f'  {m}', flush=True)

def cache_load():
    """统一读取中央去重缓存(原 split 的 bilibili_sub.json 已弃用)。"""
    p = cache_file()
    if not p.exists(): return {}
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return {}
    # 旧格式是 list，新格式是 dict(按平台分桶)
    if isinstance(data, list):
        return {'bilibili': data}
    return data

def cache_save(d):
    p = cache_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')
    return d
