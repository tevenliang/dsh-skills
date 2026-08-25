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
"""tools/bilibili.py — B站单条链接抓取 (ominicrawl v1, 工具层)

复用本 skill 内 bilibili/ (bili_feed / wbi / crawlers)；转录经 VM 路由(handoff_to_vm)交云端 FunASR,
不复制代码。总结由 pipeline 统一调用 summarize-expert, 不在平台层做。
返回统一契约: (title, author, md_path, images_dir=None)
"""
import os, sys, re, asyncio, tempfile, subprocess, shutil
from pathlib import Path
from datetime import datetime

# ── 借用本 skill 内程序模块 (subscription 代码已拷入本 skill root) ──
SKILL_ROOT = str(Path(__file__).resolve().parent.parent)
for _p in (SKILL_ROOT, os.path.join(SKILL_ROOT, "bilibili"),
          os.path.join(SKILL_ROOT, "common"),
          os.path.join(SKILL_ROOT, "lib", "douyin_api")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bili_feed import _load_bili_cookie, audio_to_wav, to_yymmdd, yml_escape
from crawlers.bilibili.web.web_crawler import BilibiliWebCrawler
from common.util import sanitize, resolve_short_url
# crawl 3.1.0: VM 转录路由（bilibili/douyin 音频交 VM 处理）
from tools.handoff_vm import handoff_to_vm, vm_routing_enabled

# 修 #18 (2026-08-01): 失败 wav 跨 batch retry 持久化目录
# 2026-08-02 修: 之前 #18 改 crawl.py:process_video() 不生效,
#   因为 watchlist 走本文件 process_one() 而不是 crawl.py:process_video().
#   现在补上: watchlist 失败的 wav 也持久化, 跨 batch retry 直接喂 wav.
PENDING_AUDIO_DIR = (Path(__file__).resolve().parent.parent / 'state' / 'pending_audio' / 'bilibili')
PENDING_AUDIO_DIR.mkdir(parents=True, exist_ok=True)




def extract_bvid(url):
    m = re.search(r'BV[0-9A-Za-z]+', url)
    if m:
        return m.group(0)
    return None


async def process_one_meta(bvid, out_dir):
    """阶段 B: 只拆元数据 + 记录 audio_url, 不调 transcribe.
    写入的 md 含 transcript_pending:true + audio_url, 给 stage2 worker 使用.
    返回 (title, author, md_path, audio_url | None).
    """
    crawler = BilibiliWebCrawler()
    detail = await crawler.fetch_one_video(bvid)
    d = detail.get('data', {}) if isinstance(detail, dict) else {}
    if not d:
        print(f"  ⏭️  fetch_one_video 无 data (BV={bvid}, resp={str(detail)[:120]}), 跳过本条")
        return None, None, None, None
    title = d.get('title', '') or bvid
    desc = d.get('desc', '') or ''
    stat = d.get('stat', {}) or {}
    cid = d.get('cid', 0)
    duration_s = d.get('duration', 0) or 0
    author = d.get('owner', {}) or {}
    author_name = author.get('name', '') or '未知UP'
    author_mid = str(author.get('mid', '') or '')
    likes = stat.get('like', 0) or 0
    comments = stat.get('reply', 0) or 0
    favorites = stat.get('favorite', 0) or 0
    pubdate = d.get('pubdate', 0) or 0
    if not (1000000000 <= pubdate <= 4102444800):
        pubdate = 0
    pub_iso = datetime.fromtimestamp(pubdate).strftime('%Y-%m-%dT%H:%M:%S') if pubdate \
        else datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

    yymmdd = to_yymmdd(pubdate)
    safe = f'{yymmdd}-{sanitize(title)}'
    out_dir_p = Path(out_dir)
    out_dir_p.mkdir(parents=True, exist_ok=True)
    orig_md = str(out_dir_p / (safe + '.md'))

    audio_url = ''
    try:
        pu = await crawler.fetch_video_playurl(bv_id=bvid, cid=str(cid), qn='64')
        pdata = pu.get('data', {}) if isinstance(pu, dict) else {}
        dash = pdata.get('dash', {}) if isinstance(pdata, dict) else {}
        audios = dash.get('audio', []) if isinstance(dash, dict) else []
        if audios:
            audio_url = audios[0].get('baseUrl', '') or audios[0].get('base_url', '')
    except Exception as e:
        print(f'  [playurl warn] {e}')

    fm = ['---',
          f'title: {yml_escape(title)}',
          f'publish_time: {pub_iso}',
          'category: bilibili',
          f'source_url: https://www.bilibili.com/video/{bvid}',
          f'uid: {bvid}',
          f'author: {yml_escape(author_name)}',
          f'author_id: {author_mid}',
          f'duration: {duration_s}',
          'transcript_pending: true',
          'transcript_available: false',
          f'audio_url: {audio_url or ""}']
    if likes:
        fm.append(f'likes: {likes}')
    if comments:
        fm.append(f'comments: {comments}')
    if favorites:
        fm.append(f'favorites: {favorites}')
    fm.append('source: bilibili-v3-ominicrawl')
    fm.append(f'created: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}')
    fm.append(f'bvid: {bvid}')
    fm.append(f'mid: {author_mid}')
    fm += ['---', '', '## 描述', '', desc.strip() or title, '']
    Path(orig_md).write_text('\n'.join(fm), encoding='utf-8')
    print(f'  → 写入 {Path(orig_md).name} (元数据, 待转录)')
    return title, author_name, orig_md, audio_url or None


async def process_one(bvid, out_dir):
    """向后兼容: 阶段 B 元数据 → 阶段 2 转录 → 阶段 3 写回.
    本身仍是串行 (用于 clip 单条 / 其他老路径), watchlist 会走队列化路径.
    """
    title, author, md_path, audio_url = await process_one_meta(bvid, out_dir)
    if not md_path or not audio_url:
        return title, author, md_path, None

    cookie = _load_bili_cookie()
    hdrs = ('User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36\r\n'
            f'Referer: https://www.bilibili.com/video/{bvid}/\r\n'
            f'Cookie: {cookie}\r\n')
    preview_note = ''
    transcript = ''
    transcribe_source = ''
    duration_s = 0
    publish_date = ''
    desc_text = ''
    try:
        with open(md_path, encoding='utf-8') as _f:
            _mtxt = _f.read()
        _m = re.search(r'^duration:\s*(\d+)', _mtxt, re.M)
        if _m:
            duration_s = int(_m.group(1))
        _m2 = re.search(r'^publish_time:\s*(\S+)', _mtxt, re.M)
        if _m2:
            publish_date = _m2.group(1)[:10]
        _m3 = re.search(r'^## 描述\s*\n(.*?)(?=\n## |\Z)', _mtxt, re.S)
        if _m3:
            desc_text = _m3.group(1).strip()
    except Exception:
        pass

    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, 'v.wav')
        if audio_to_wav(audio_url, wav, headers=hdrs):
            # ── crawl 3.1.0: VM 转录路由（唯一 ASR 路径，无本地/在线回退）──
            if vm_routing_enabled("bilibili"):
                ok = handoff_to_vm(
                    wav, platform="bilibili", video_id=bvid,
                    title=title, author=author,
                    source_url=f"https://www.bilibili.com/video/{bvid}",
                    publish_date=publish_date, desc=desc_text,
                )
                if ok:
                    # 已上传 VM，转录/总结/发布全交 VM；返回 md=None 让上层跳过发布
                    print(f'  → 已交 VM 处理 (bvid={bvid}), 跳过本地转录')
                    return title, author, None, None
                # VM 上传失败：持久化 wav 供后续 backfill 重试，跳过本条（仅 VM 路径，无本地 ASR）
                print(f'  ⚠️ [HANDOFF.FAIL] 上传 VM 失败, 持久化 wav 供重试并跳过 (bvid={bvid})')
                try:
                    _sz_mb = os.path.getsize(wav) / 1024 / 1024
                    _pending = PENDING_AUDIO_DIR / f'{bvid}.wav'
                    shutil.copy2(wav, _pending)
                    print(f'  [persist] wav {_sz_mb:.1f}MB -> PENDING_AUDIO_DIR/{bvid}.wav')
                except Exception as _mv_e:
                    print(f'  ⚠️ wav 持久化失败: {_mv_e}')
                return title, author, None, None
            # vm_asr_routing=false 时本地 ASR 已停用（仅 VM 路径），跳过转录
            print(f'  ⚠️ [ASR.OFF] vm_asr_routing=false, 本地 ASR 已停用(仅 VM 路径), 跳过转录 (bvid={bvid})')
            return title, author, None, None
        else:
            print('  [音频下载失败] 可能 cookie/ticket 过期, 仅落元数据')

    print(f'  → 写入 {Path(md_path).name}')
    return title, author, md_path, None


def crawl(url, tmp_dir, timeout=600):
    bvid = extract_bvid(url)
    if not bvid:
        # B站「复制链接」短链 (b23.tv/xxx) 需先解析重定向
        resolved = resolve_short_url(url)
        bvid = extract_bvid(resolved)
    if not bvid:
        raise RuntimeError(f"无法从 URL 提取 BV 号: {url}")
    print(f'🎬 B站视频 {bvid}')
    title, author, md, images = asyncio.run(process_one(bvid, tmp_dir))
    if title is None:
        # B1 fix: 单条失败 (BV -404/接口拒答) → 返回 None, 上层 skip 继续
        return None, None, None, None
    return title, author, md, images


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) < 3:
        print("用法: python bilibili.py <URL> <tmp_dir>")
        _sys.exit(1)
    t, a, m, i = crawl(_sys.argv[1], _sys.argv[2])
    print(f"title={t}\nauthor={a}\nmd={m}")
