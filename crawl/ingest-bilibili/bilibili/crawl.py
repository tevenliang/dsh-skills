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
"""fetch_bili_v3.py — B站博主视频抓取 (v3.1, 支持 USE_VM 开关)
用法: fetch_bili_v3.py <mid> <name> [out_dir]

USE_VM=true: 仅落元数据, 转录由 VM daemon 完成
USE_VM=false: Mac 本地转录 (Groq → faster-whisper), 写完正文
"""

import sys as _sys
from pathlib import Path as _P
_SKILL_ROOT = str(_P(__file__).resolve().parent.parent)
if _SKILL_ROOT not in _sys.path:
    _sys.path.insert(0, _SKILL_ROOT)

import sys, os, json, asyncio, shutil, subprocess, tempfile, time, uuid
from pathlib import Path
from datetime import datetime

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SKILL_DIR = os.path.dirname(_SCRIPT_DIR)
LLM_SCR = os.path.join(_SKILL_DIR, "common", "llm.py")
sys.path.insert(0, _SCRIPT_DIR)
sys.path.insert(0, os.path.join(_SKILL_DIR, 'lib', 'douyin_api'))
sys.path.insert(0, os.path.join(_SKILL_DIR, 'scripts'))

from bili_feed import (
    _detect_vault, _load_bili_cookie, audio_to_wav, dedup, to_yymmdd,
    log, cache_load, cache_save, yml_escape,
)
from wbi import BilibiliWbi
from crawlers.bilibili.web.web_crawler import BilibiliWebCrawler
from common.transcribe import transcribe, load_config, USE_VM as _USE_VM_CONFIG
from common.paths import notes_dir
from common.util import sanitize

PARALLEL = 1 # 2026-07-31: 实测 PARALLEL=3 + 10 帖卡死 (Groq 3 路并发), 1 顺序跑 10 帖 12-15min 稳定; 用户偏好低 Mac 资源 (issue #12)
VM       = 'vm'
SSH_OPTS = ['-o', 'StrictHostKeyChecking=no', '-o', 'ConnectTimeout=10']

def _get_use_vm():
    """读取 USE_VM 开关: 环境变量 > config.yaml > True"""
    env_vm = os.environ.get("USE_VM", "")
    if env_vm.lower() in ("true", "1", "yes"):
        return True
    if env_vm.lower() in ("false", "0", "no"):
        return False
    return _USE_VM_CONFIG  # config.yaml 默认

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
log(f"USE_VM={USE_VM}  LIMIT={LIMIT}")

# 修 #18 (2026-08-01): wav 持久化目录 (失败 wav 跨 batch retry 用)
PENDING_AUDIO_DIR = _P(__file__).resolve().parents[2] / "state" / "pending_audio" / "bilibili"  # crawl/state/pending_audio/bilibili
PENDING_AUDIO_DIR.mkdir(parents=True, exist_ok=True)

async def process_video(v, name, out_dir, sem, crawler, deferred=None):
    async with sem:
        bvid = v['bvid']; title = v['title']
        mid  = str(v.get('mid', ''))
        log(f'  [{bvid}] {title[:40]}')

        yymmdd = to_yymmdd(v.get('created',''))
        safe   = f'{yymmdd}-{sanitize(title)}'
        out_dir_p = Path(out_dir)
        orig_md = str(out_dir_p / (safe + '.md'))

        # 已含正文说明转录已完成
        if Path(orig_md).exists():
            body = Path(orig_md).read_text(encoding='utf-8',errors='replace')
            if '## 正文' in body and len(body.split('## 正文',1)[1].split('## ')[0].strip()) > 50:
                log(f'    已存在有正文, skip'); return 'skip',''

        # 获取视频详情
        try:
            detail = await crawler.fetch_one_video(bvid)
            d = detail.get('data',{}) if isinstance(detail,dict) else {}
            desc       = d.get('desc','')
            stat       = d.get('stat',{}) or {}
            cid        = d.get('cid',0)
            duration_s = d.get('duration',0) or 0
            author     = d.get('owner',{}) or {}
            author_mid = str(author.get('mid',mid))
            likes      = stat.get('like',0) or 0
            comments   = stat.get('reply',0) or 0
            favorites  = stat.get('favorite',0) or 0
            pubdate    = d.get('pubdate',0) or 0
            # 边界防护: pubdate=0 或非法(过小/过大) → 归一为 0, 避免 1970 或离谱日期
            if not (1000000000 <= pubdate <= 4102444800):
                pubdate = 0
        except Exception as e:
            return 'fail',f'detail:{e}'

        pub_iso = datetime.fromtimestamp(pubdate).strftime('%Y-%m-%dT%H:%M:%S') if pubdate else datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

        # USE_VM=true → 仅落元数据，转录走 VM daemon
        if USE_VM:
            out_md = dedup(orig_md)
            fm = ['---']
            fm += [f'title: {yml_escape(desc or title)}', f'publish_time: {pub_iso}',
                   'category: bilibili', f'source_url: https://www.bilibili.com/video/{bvid}',
                   f'uid: {bvid}', f'author: {yml_escape(name)}',
                   f'author_id: {author_mid}', 'transcript_available: false',
                   'status: ["transcribing", "summarizing", "abstracting"]',
                   f'source: bilibili-v3', f'created: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}',
                   f'bvid: {bvid}', f'mid: {author_mid}', '---', '',
                   '## 描述', '', str(desc or '').strip() or title, '']
            out_dir_p.mkdir(parents=True, exist_ok=True)
            Path(out_md).write_text('\n'.join(fm), encoding='utf-8')
            log(f'    VM 模式-仅落盘 {Path(out_md).name}')
            return 'ok', ''

        # USE_VM=false → Mac 本地转录
        audio_url = ''
        try:
            pu = await crawler.fetch_video_playurl(bv_id=bvid, cid=str(cid), qn='64')
            pdata = pu.get('data',{}) if isinstance(pu,dict) else {}
            dash   = pdata.get('dash',{})
            audios = dash.get('audio',[])
            if audios: audio_url = audios[0].get('baseUrl','') or audios[0].get('base_url','')
        except Exception as e:
            log(f'    playurl warn:{e}')

        transcript = ''
        transcribe_source = ''
        if audio_url:
            _cookie = _load_bili_cookie()
            hdrs = ('User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36\r\n'
                    f'Referer: https://www.bilibili.com/video/{bvid}/\r\n'
                    f'Cookie: {_cookie}\r\n')
            with tempfile.TemporaryDirectory() as tmp:
                wav = os.path.join(tmp, 'v.wav')
                t0 = time.time()
                ok = audio_to_wav(audio_url, wav, headers=hdrs)
                if ok:
                    sz = os.path.getsize(wav)/1024/1024
                    log(f'    wav {sz:.1f}MB ({time.time()-t0:.1f}s)')
                    # 极简模式 (2026-07-30): catch Groq raise, 单条不杀整批
                    try:
                        transcript, transcribe_source = transcribe(wav)
                        # 修 #18 (2026-08-01): 转录成功 → 清 PENDING_AUDIO_DIR 里同 bvid 的 wav (上次失败留下的)
                        _pending = PENDING_AUDIO_DIR / f'{bvid}.wav'
                        if _pending.exists():
                            _pending.unlink()
                    except RuntimeError as e:
                        log(f'    ⚠️ [ASR.FATAL] Groq 转录失败, 跳过 (bvid={bvid}): {e}')
                        transcript, transcribe_source = '', 'fatal'
                        # 修 #16 (2026-08-01): 极简版 transcribe() 不再自动 append deferred,
                        # caller 手动入队才能让 end-of-batch retry 工作. 修复 cooldown 后不回补 bug.
                        if deferred is not None and audio_url:
                            # 修 #18: 失败 wav 持久化到 PENDING_AUDIO_DIR (跨 batch retry 直接喂 wav,
                            # 跳过流式下载 + 抽音频, 绕过 524 timeout)
                            _pending = PENDING_AUDIO_DIR / f'{bvid}.wav'
                            try:
                                shutil.copy2(wav, _pending)
                                _wav_persisted = str(_pending)
                                log(f'    [persist] wav {sz:.1f}MB -> PENDING_AUDIO_DIR/{bvid}.wav')
                            except Exception as _mv_e:
                                _wav_persisted = None
                                log(f'    ⚠️ wav 持久化失败: {_mv_e}')
                            deferred.append({
                                'bvid': bvid,
                                'audio_url': audio_url,
                                'headers': hdrs,
                                'out_md': str(out_md),
                                'wav_path': _wav_persisted,
                            })
                    log(f'    转录: {transcribe_source}, {len(transcript)} 字')
                else:
                    log(f'    [音频下载失败] upos/mcdn 下载或转码失败')

        # 已存在(orig_md 为 VM 模式无正文历史 md) → 覆盖原文件补转录, 不新建 _N
        # 配合上方 skip(有正文即跳过), 避免无限重抓 + _N 垃圾
        out_md = orig_md if Path(orig_md).exists() else dedup(orig_md)
        fm = [
            '---',
            f'title: {yml_escape(title)}',
            f'publish_time: {pub_iso}',
            'category: bilibili',
            f'source_url: https://www.bilibili.com/video/{bvid}',
            f'uid: {bvid}',
            f'author: {name}',
            f'author_id: {author_mid}',
            f'duration: {duration_s}',
        ]
        if transcript:
            fm.append(f'transcript_source: {transcribe_source}')
            fm.append('transcript_available: true')
            fm.append('transcript_pending: false')
        else:
            fm.append('transcript_source: ""')
            fm.append('transcript_available: false')
            fm.append('transcript_pending: true')
        if likes:     fm.append(f'likes: {likes}')
        if comments:   fm.append(f'comments: {comments}')
        if favorites:  fm.append(f'favorites: {favorites}')
        fm += [
            'status: ["transcribing", "summarizing", "abstracting"]' if transcript else 'status: ["summarizing", "abstracting"]',
            'source: bilibili-v3',
            f'created: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}',
            f'bvid: {bvid}',
            f'mid: {author_mid}',
            '---','',
            '## 描述','', str(desc or '').strip() or '_无描述_','',
        ]
        if transcript:
            fm += ['## 正文','', transcript,'']
        Path(out_md).write_text('\n'.join(fm), encoding='utf-8')
        log(f'    写入 {Path(out_md).name} ({len(transcript)} 字)')

        # 转录成功后立刻总结+速读
        if transcript:
            log(f'    → 总结中... ')
            try:
                llm_r = subprocess.run(
                    [sys.executable, LLM_SCR, out_md],
                    capture_output=True, text=True, timeout=180
                )
                if llm_r.returncode == 0:
                    log('✅')
                else:
                    log(f'(稍后: {llm_r.stderr.strip()[:60]})')
            except subprocess.TimeoutExpired:
                log('(超时, batch 兜底)')
            except Exception as e:
                log(f'(异常: {e})')

        return 'ok',''

def _scan_pending_bili():
    """修 #18 (2026-08-01): 启动时扫描 PENDING_AUDIO_DIR 里残留 wav,
    加入本批 deferred (跨 batch retry). 不删 wav, 只读 metadata + wav_path."""
    items = []
    if not PENDING_AUDIO_DIR.exists():
        return items
    for wav in PENDING_AUDIO_DIR.glob('*.wav'):
        bvid = wav.stem
        items.append({
            'bvid': bvid,
            'audio_url': '',  # 跨 batch 不重抽, 直接喂 wav
            'headers': '',
            'out_md': '',
            'wav_path': str(wav),
        })
    return items


async def _retry_bili_deferred(deferred):
    """修 #16 + #18 (2026-08-01): batch 结束前 retry 所有 deferred 项.

    修 #16: 极简版 transcribe() raise-only, batch 末尾 retry.
    修 #18: 优先用 wav_path (PENDING_AUDIO_DIR) 直接喂 wav,
    没有 wav_path 才流式重抽 audio_url.
    返回 (retry_ok, retry_fail), 调用方负责 apply_transcript 注入文本 + 缓存.
    """
    retry_ok, retry_fail = [], []
    for item in deferred:
        bvid = item.get('bvid', 'unknown')
        wav_path = item.get('wav_path', '')
        audio_url = item.get('audio_url', '')
        try:
            # 修 #18: 优先用 wav_path (持久化 wav, 跳过流式抽音频)
            if wav_path and os.path.exists(wav_path):
                text, src_tag = transcribe(wav_path)
            elif audio_url:
                text, src_tag = transcribe(audio_url, headers=item.get('headers'))
            else:
                retry_fail.append({'bvid': bvid, 'error': 'no wav_path or audio_url'})
                continue
            if text:
                retry_ok.append({'bvid': bvid, 'transcript': text,
                                 'source': src_tag, 'md_path': item.get('out_md', '')})
            else:
                retry_fail.append({'bvid': bvid, 'error': 'transcribe() returned empty'})
        except Exception as e:
            retry_fail.append({'bvid': bvid, 'error': str(e)})
    return retry_ok, retry_fail


async def main(mid, name, out_dir):
    from common.transcribe import apply_transcript
    from common.fetch_log import append_fetch_log as _append_log
    log(f'=== {name} (mid={mid}) ===')
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    cache = cache_load(); bili_list = cache.setdefault('bilibili',[])
    log(f'  cache {len(bili_list)} bvid')

    crawler = BilibiliWebCrawler()
    cookie  = _load_bili_cookie()
    async with BilibiliWbi(cookie=cookie) as bili_wbi:
        data = await bili_wbi.fetch_user_post_videos(mid=str(mid), pn=1)
    vlist = data.get('data',{}).get('list',{}).get('vlist',[])[:LIMIT]
    log(f'  vlist:{len(vlist)}')

    deferred = []  # 修 #16 (2026-08-01): transcribe() 失败的 bvid 在 batch 末尾 retry
    # 修 #18 (2026-08-01): 启动 scan PENDING_AUDIO_DIR 残留 wav, 加入本批 deferred (跨 batch retry)
    _pending_bili = _scan_pending_bili()
    if _pending_bili:
        deferred.extend(_pending_bili)
        log(f'  📂 PENDING_AUDIO_DIR: {len(_pending_bili)} 个残留 wav 跨 batch retry')

    sem = asyncio.Semaphore(PARALLEL)
    results = await asyncio.gather(
        *[process_video(v,name,out,sem,crawler,deferred) for v in vlist],
        return_exceptions=True)
    # 修 #16: 收集 v 与结果配对, 用于精确只 cache 成功 bvid
    paired = list(zip(vlist, results))

    ok=fail=skip=0
    success_bvs = []  # 修 #16: 只 cache 成功转录的 bvid, 失败不入 cache 以便下次 retry
    for v, r in paired:
        if isinstance(r,tuple):
            if r[0]=='ok':    ok+=1; success_bvs.append(v.get('bvid',''))
            elif r[0]=='skip': skip+=1; success_bvs.append(v.get('bvid',''))  # skip=MD已存在, 也算 cache
            elif r[0]=='fail':fail+=1
            # 2026-08-19 hotfix: 逐条写 Mac 本地下载台账 (bilibili 此前只在博主级记一次)
            if r[0] in ('ok','skip') and v.get('bvid'):
                _append_log(platform='bilibili', uid=v.get('bvid'), md_abs_path='',
                            blogger=name, title=v.get('title',''))
    log(f'  ok={ok} skip={skip} fail={fail} pending={len(deferred)}')

    # 修 #16: batch 末尾 retry deferred (cooldown 后回补)
    if deferred:
        log(f'🔁 batch retry deferred: {len(deferred)} 条')
        retry_ok, retry_fail = await _retry_bili_deferred(deferred)
        for item in retry_ok:
            if item.get('md_path') and item.get('transcript'):
                apply_transcript(item['md_path'], item['transcript'], source=item.get('source', ''))
                if item.get('bvid') and item['bvid'] not in bili_list:
                    bili_list.append(item['bvid'])
                ok += 1
                log(f'  [retry ok] {item["bvid"][:12]} {len(item["transcript"])} 字')
        for item in retry_fail:
            log(f'  [retry fail] {item["bvid"][:12]}: {item["error"][:80]}')
    log(f'  ok={ok} skip={skip} fail={fail} (含 retry)')

    # 修 #16: cache 只入成功项 (避免失败 bvid 永远被 skip)
    for bv in success_bvs:
        if bv and bv not in bili_list:
            bili_list.append(bv)

    cache_save(cache)

if __name__=='__main__':
    if len(sys.argv)<3: print('usage: fetch_bili_v3.py <mid> <name> [out_dir]'); sys.exit(1)
    mid=sys.argv[1]; name=sys.argv[2]
    out_dir=sys.argv[3] if len(sys.argv)>3 else str(notes_dir()/'bilibili'/name)
    asyncio.run(main(mid,name,out_dir))
