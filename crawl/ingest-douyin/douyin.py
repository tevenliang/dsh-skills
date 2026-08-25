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
"""tools/douyin.py — 抖音单条链接抓取 (ominicrawl v1, 工具层)

复用本 skill 内 douyin/ + lib/douyin_api；转录经 VM 路由(handoff_to_vm)交云端 FunASR,
返回统一契约: (title, author, md_path, images_dir=None)
"""
import os, sys, re, asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta

SKILL_ROOT = str(Path(__file__).resolve().parent.parent)
for _p in (SKILL_ROOT, os.path.join(SKILL_ROOT, "douyin"),
          os.path.join(SKILL_ROOT, "common"),
          os.path.join(SKILL_ROOT, "lib", "douyin_api")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from crawlers.douyin.web.web_crawler import DouyinWebCrawler
from common.util import sanitize, to_yymmdd, yml_escape, fld, resolve_short_url
# crawl 3.1.0: VM 转录路由（bilibili/douyin 音频交 VM 处理）
from tools.handoff_vm import handoff_to_vm, vm_routing_enabled


def extract_aweme_id(url):
    m = re.search(r'/video/(\d+)', url)
    if m:
        return m.group(1)
    # 短链兜底: iesdouyin 分享页把 id 放在路径里
    m2 = re.search(r'/(\d{15,20})', url)
    return m2.group(1) if m2 else None


async def process_one_meta(aweme_id, out_dir):
    """阶段 B: 只拆元数据 + 记录 video_url, 不调 transcribe.
    写入的 md 含 transcript_pending:true + audio_url (douyin 叫 video_url, 复用 audio_url key 以对齐),
    给 stage2 worker 使用. 返回 (title, author, md_path, video_url | None).
    """
    crawler = DouyinWebCrawler()
    detail = await crawler.fetch_one_video(aweme_id)
    if isinstance(detail, dict):
        # P1-2 fix (2026-07-16): 严格判断 - 只在 aweme_detail 存在且含 desc/author 时放过.
        # 原 'or detail' fallback 会让空 dict 幫装非空, 写出 '(无标题)' 空笔记.
        aweme = detail.get('aweme_detail')
        if not isinstance(aweme, dict) or not (aweme.get('desc') or aweme.get('author')):
            sc = detail.get('status_code', 'N/A')
            print(f"  ⏭️  fetch_one_video 无有效 aweme_detail (status_code={sc}, 可能 cookie 过期), 跳过本条")
            return None, None, None, None
    else:
        # P1-2 fix: detail 非 dict (接口异常) → 跳过
        print(f"  ⏭️  fetch_one_video 返回非 dict ({type(detail).__name__}), 跳过本条")
        return None, None, None, None

    desc = fld(aweme.get('desc', '')) or '(无标题)'
    publish_ms = aweme.get('create_time', 0)
    TZ = timezone(timedelta(hours=8))
    publish_iso = datetime.fromtimestamp(publish_ms, TZ).strftime('%Y-%m-%dT%H:%M:%S') if publish_ms \
        else datetime.now(TZ).strftime('%Y-%m-%dT%H:%M:%S')
    stats = aweme.get('statistics', {}) or {}
    likes = stats.get('digg_count', 0) or 0
    comments = stats.get('comment_count', 0) or 0
    favorites = stats.get('collect_count', 0) or 0
    shares = stats.get('share_count', 0) or 0
    duration_ms = (aweme.get('video', {}) or {}).get('duration', 0) or 0
    author_name = (aweme.get('author', {}) or {}).get('nickname', '') or '未知作者'

    video_url = ''
    try:
        vl = aweme.get('video', {}) or {}
        video_url = (vl.get('play_addr', {}) or {}).get('url_list', [None])[0] or \
                    (vl.get('download_addr', {}) or {}).get('url_list', [None])[0] or ''
    except Exception:
        pass

    yymmdd = to_yymmdd(publish_ms)
    safe = f'{yymmdd}-{sanitize(desc)}'
    out_dir_p = Path(out_dir)
    out_dir_p.mkdir(parents=True, exist_ok=True)
    orig_md = str(out_dir_p / (safe + '.md'))
    source_url = f'https://www.douyin.com/video/{aweme_id}'

    fm = ['---',
          f'title: {yml_escape(desc)}',
          f'publish_time: {publish_iso}',
          'category: douyin',
          f'source_url: {source_url}',
          f'uid: {aweme_id}',
          f'author: {yml_escape(author_name)}']
    if duration_ms:
        fm.append(f'duration: {duration_ms//1000}')
    # 阶段 B 主要区别: 加 transcript_pending + audio_url (stage2 用)
    fm.append('transcript_pending: true')
    fm.append('transcript_available: false')
    fm.append(f'audio_url: {video_url or ""}')
    if likes:
        fm.append(f'likes: {likes}')
    if comments:
        fm.append(f'comments: {comments}')
    if favorites:
        fm.append(f'favorites: {favorites}')
    if shares:
        fm.append(f'shares: {shares}')
    fm.append('source: douyin_api-ominicrawl')
    fm.append(f'created: {datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S")}')
    fm.append(f'aweme_id: {aweme_id}')
    fm += ['---', '', f'## {desc}']
    Path(orig_md).write_text('\n'.join(fm), encoding='utf-8')
    print(f'  → 写入 {Path(orig_md).name} (元数据, 待转录)')
    return desc, author_name, orig_md, video_url or None


def _download_douyin_audio(video_url, out_wav, headers):
    """下载抖音视频音频并转 16k mono wav（供 VM FunASR 使用）。

    Returns: bool 成功
    """
    import subprocess
    import urllib.request
    mp4 = out_wav + ".mp4"
    try:
        req = urllib.request.Request(video_url, headers=headers)
        # 2026-08-15: urllib 默认不读 macOS 系统代理, 直连 douyin.com 会被 IP 风控 403.
        # 强制走 Clash 7897 (与浏览器一致) 拿到代理节点 IP 才能通过抖音风控.
        # 与 config.yaml proxies 同步恢复 (8/7 cc78ca7 改 null 是当时 Clash 退出).
        from urllib.request import ProxyHandler, build_opener
        proxy_handler = ProxyHandler({
            "http":  "http://127.0.0.1:7897",
            "https": "http://127.0.0.1:7897",
        })
        opener = build_opener(proxy_handler)
        with opener.open(req, timeout=180) as resp, open(mp4, "wb") as f:
            f.write(resp.read())
        if not os.path.exists(mp4) or os.path.getsize(mp4) < 1024:
            return False
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", mp4,
             "-vn", "-ac", "1", "-ar", "16000", out_wav],
            capture_output=True, timeout=300,
        )
        return r.returncode == 0 and os.path.exists(out_wav) and os.path.getsize(out_wav) > 0
    except Exception as e:
        print(f'  ⚠️ [handoff] douyin 下载/转码失败: {e}')
        return False
    finally:
        try:
            os.unlink(mp4)
        except Exception:
            pass


async def process_one(aweme_id, out_dir):
    """向后兼容: 阶段 B 元数据 → 阶段 2 转录 → 阶段 3 写回.
    本身仍是串行 (用于 clip 单条 / 其他老路径), watchlist 会走队列化路径.
    """
    desc, author, md_path, video_url = await process_one_meta(aweme_id, out_dir)
    if not md_path:
        return desc, author, md_path, None
    transcript = ''
    transcribe_source = ''
    if video_url:
        dy_headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Referer': 'https://www.douyin.com/',
        }
        # ── crawl 3.1.0: VM 转录路由（唯一 ASR 路径，无本地/在线回退）──
        if vm_routing_enabled("douyin"):
            local_wav = os.path.join(out_dir, f"{aweme_id}.wav")
            if _download_douyin_audio(video_url, local_wav, dy_headers):
                publish_date = ""
                try:
                    with open(md_path, encoding='utf-8') as _f:
                        _mt = _f.read()
                    _m = re.search(r'^publish_time:\s*(\S+)', _mt, re.M)
                    if _m:
                        publish_date = _m.group(1)[:10]
                except Exception:
                    pass
                ok = handoff_to_vm(
                    local_wav, platform="douyin", video_id=aweme_id,
                    title=desc, author=author,
                    source_url=f"https://www.douyin.com/video/{aweme_id}",
                    publish_date=publish_date, desc=desc,
                )
                if ok:
                    print(f'  → 已交 VM 处理 (aweme={aweme_id}), 跳过本地转录')
                    try:
                        os.unlink(local_wav)
                    except Exception:
                        pass
                    return desc, author, None, None
                # VM 上传失败：清理本地 wav，跳过本条（仅 VM 路径，无本地 ASR）
                print(f'  ⚠️ [HANDOFF.FAIL] 上传 VM 失败, 跳过 (aweme={aweme_id})')
                try:
                    os.unlink(local_wav)
                except Exception:
                    pass
                return desc, author, None, None
            else:
                print(f'  ⚠️ [HANDOFF.FAIL] douyin 音频下载失败, 跳过 (aweme={aweme_id})')
                return desc, author, None, None
        # vm_asr_routing=false 时本地 ASR 已停用（仅 VM 路径），跳过转录
        print(f'  ⚠️ [ASR.OFF] vm_asr_routing=false, 本地 ASR 已停用(仅 VM 路径), 跳过转录 ({aweme_id})')
        return desc, author, md_path, None
    print(f'  → 写入 {Path(md_path).name} ({len(transcript)} 字转录)')
    return desc, author, md_path, None




def crawl(url, tmp_dir, timeout=600):
    """抓取单个抖音视频 URL；博主主页展开由 crawl.py watchlist 统一负责。"""
    aweme_id = extract_aweme_id(url)
    if not aweme_id:
        # 抖音「复制链接」短链 (v.douyin.com/xxx) 需先解析重定向
        resolved = resolve_short_url(url)
        aweme_id = extract_aweme_id(resolved)
    if not aweme_id:
        raise RuntimeError(f"无法从 URL 提取 aweme_id: {url}")

    print(f'🎬 抖音视频 {aweme_id}')
    title, author, md, images = asyncio.run(process_one(aweme_id, tmp_dir))
    if title is None:
        # 单条失败 (接口拒答/cookie 过期) → 返回 None, 上层 skip 继续
        return None, None, None, None
    return title, author, md, images


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) < 3:
        print("用法: python douyin.py <URL> <tmp_dir>")
        _sys.exit(1)
    t, a, m, i = crawl(_sys.argv[1], _sys.argv[2])
    print(f"title={t}\nauthor={a}\nmd={m}")
