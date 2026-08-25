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
fetch_url_xhs_v2.py - opencli 方案抓单条小红书 URL
  - 走副 profile (dy2s6y2k) Chrome 登录态
  - 从 URL 提取 note_id + xsec_token
  - 浏览器 navigate + eval __INITIAL_STATE__ 拿全字段
  - frontmatter v1.4 schema; status: ocring
  - 缓存 .subscription-crawl-cache.json
  - 写 fetch.log 给 VM subscription-expert

用法: fetch_url_xhs_v2.py <url> <blogger> <out_dir> [note_id_override]
"""

import sys as _sys
from pathlib import Path as _P
_SKILL_ROOT = str(_P(__file__).resolve().parent.parent)
if _SKILL_ROOT not in _sys.path:
    _sys.path.insert(0, _SKILL_ROOT)

import os
import sys
import re
import json
import hashlib
import urllib.request
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta
from common.fetch_log import append_fetch_log as _append_log, _detect_share
from common.paths import media_dir, notes_dir, cache_file

TZ = timezone(timedelta(hours=8))
PLATFORM = "xiaohongshu"
CATEGORY = "xhs"
SOURCE = "opencli"
OPENCLI_PROFILE = os.environ.get("OPENCLI_PROFILE", "dy2s6y2k")
BROWSER_SESSION = "xhs_url"
SHARE = _detect_share()
CACHE_FILE = cache_file()


def log(m):
    print(f"  {m}", flush=True)


def fail(m):
    print(f"FAIL  {m}", flush=True)
    sys.exit(1)


from common.util import (
    sanitize,
    to_yymmdd,
    yml_escape,
    dedup,
    cache_load,
    cache_save,
    fld,
    _parse_count,
    run_opencli,
)


def extract_note_id_from_url(url):
    """从 explore/user URL 提取 note id (24 hex)"""
    # /explore/6a45d2d3000000002101afdd 或 /user/profile/xxx/6a45d2d3000000002101afdd
    m = re.search(r"/(explore|discovery/item)/([0-9a-f]{20,30})", url)
    if m:
        return m.group(2)
    m = re.search(r"/([0-9a-f]{24,30})(?:[?&#]|$)", url)
    if m:
        return m.group(1)
    return None


def fetch_note_detail(feed_url):
    out = run_opencli(["browser", BROWSER_SESSION, "open", feed_url], timeout=30)
    if not out:
        return None
    import time
    time.sleep(1.5)
    js = (
        "(function(){try{var s=window.__INITIAL_STATE__;"
        "if(!s||!s.note||!s.note.noteDetailMap)return JSON.stringify({err:'no_state'});"
        "var ks=Object.keys(s.note.noteDetailMap);if(!ks.length)return JSON.stringify({err:'no_note'});"
        "var n=s.note.noteDetailMap[ks[0]].note;if(!n)return JSON.stringify({err:'no_inner'});"
        "var v=n.video&&n.video.media&&n.video.media.stream&&n.video.media.stream.h264;"
        "var v0=v&&v[0];"
        "return JSON.stringify({"
        "time:n.time,lastUpdateTime:n.lastUpdateTime,type:n.type,title:n.title,desc:n.desc,ipLocation:n.ipLocation,"
        "tagList:(n.tagList||[]).map(function(t){return t.name;}),"
        "imageList:(n.imageList||[]).map(function(i){return {urlDefault:i.urlDefault,urlPre:i.urlPre,width:i.width,height:i.height};}),"
        "video:v0?{masterUrl:v0.masterUrl,backupUrls:v0.backupUrls,duration:v0.videoDuration||v0.duration,width:v0.width,height:v0.height,format:v0.format,size:v0.size}:null,"
        "interact:n.interactInfo,author:n.user&&n.user.nickname,authorId:n.user&&n.user.userId,noteId:n.noteId"
        "});}catch(e){return JSON.stringify({err:String(e)});}})()"
    )
    out = run_opencli(["browser", BROWSER_SESSION, "eval", js], timeout=30)
    if not out:
        return None
    out = re.sub(r"\n\s*Update available.*$", "", out, flags=re.DOTALL).strip()
    try:
        data = json.loads(out)
    except json.JSONDecodeError as e:
        log(f"  detail JSON parse fail: {e}; first 200: {out[:200]}")
        return None
    if data.get("err"):
        log(f"  detail err: {data['err']}")
        return None
    return data


def download_to_cache_media(url, out_dir=None):
    if not url:
        return None
    vault_media = media_dir().resolve()
    vault_media.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.xiaohongshu.com/"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
    except Exception as e:
        log(f"  下载失败 {url[:60]}: {e}")
        return None
    if len(data) < 1000:
        return None
    md5 = hashlib.md5(data).hexdigest()
    ext = ".jpg"
    if data[:4] == b"\x89PNG":
        ext = ".png"
    elif data[:2] == b"\xff\xd8":
        ext = ".jpg"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        ext = ".webp"
    elif url.lower().endswith(".png"):
        ext = ".png"
    elif url.lower().endswith(".webp"):
        ext = ".webp"
    elif url.lower().endswith(".gif"):
        ext = ".gif"
    # 单条爬的图也落 media/xhs/（与批量 xhs + 已迁移数据同源），wikilink 才对得上
    dst = vault_media / "xhs" / f"{md5}{ext}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        dst.write_bytes(data)
    # 统一用 wikilink 引用 media/xhs/, md 移动也不断链
    return f"media/xhs/{dst.name}"

def cleanup_browser():
    try:
        subprocess.run(
            ["opencli", "--profile", OPENCLI_PROFILE, "browser", BROWSER_SESSION, "close"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        pass


def main():
    if len(sys.argv) < 4:
        print(
            "usage: fetch_url_xhs_v2.py <url> <blogger> <out_dir> [note_id_override]",
            file=sys.stderr,
        )
        sys.exit(1)
    url = sys.argv[1]
    blogger = sys.argv[2]
    out_dir = Path(sys.argv[3])
    note_id_override = sys.argv[4] if len(sys.argv) > 4 else None
    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"单条抓取: blogger={blogger} url={url[:80]}")

    try:
        detail = fetch_note_detail(url)
    finally:
        cleanup_browser()
    if not detail:
        fail("拿不到笔记详情")

    note_id = note_id_override or fld(detail.get("noteId")) or extract_note_id_from_url(url)
    if not note_id:
        fail("无法解析 note_id")

    cache = cache_load().get(PLATFORM, [])
    if note_id in cache:
        log(f"[{note_id[:12]}] cached, 跳过")
        print(f"BLOGGER_OK  0 条 ok, 1 条 skip (cached)")
        return

    publish_ms = detail.get("time") or 0
    publish_iso = (
        datetime.fromtimestamp(publish_ms / 1000, TZ).strftime("%Y-%m-%dT%H:%M:%S")
        if publish_ms
        else datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S")
    )
    title = fld(detail.get("title")) or "(无标题)"
    desc = fld(detail.get("desc")) or ""
    interact = detail.get("interact") or {}
    author = fld(detail.get("author")) or blogger
    author_id = fld(detail.get("authorId"))
    ip_loc = fld(detail.get("ipLocation"))
    tag_list = detail.get("tagList") or []
    image_list = detail.get("imageList") or []
    video = detail.get("video")
    is_video = bool(video) or detail.get("type") == "video"

    likes = interact.get("likedCount") if isinstance(interact, dict) else None
    comments = interact.get("commentCount") if isinstance(interact, dict) else None
    collects = interact.get("collectedCount") if isinstance(interact, dict) else None

    media_refs = []
    if not is_video and image_list:
        for i, img in enumerate(image_list[:9]):
            url_i = img.get("urlDefault") or img.get("urlPre")
            if not url_i:
                continue
            w, h = img.get("width"), img.get("height")
            rel = download_to_cache_media(url_i, out_dir)
            if rel:
                alt = f"img_{i:02d}"
                if w and h:
                    alt = f"{alt}|{w}x{h}"
                media_refs.append(f"![[{rel}]]")
    elif is_video and video:
        master = video.get("masterUrl") or (video.get("backupUrls") or [None])[0]
        dur = video.get("duration") or 0
        dur_str = f"{dur // 60000}:{(dur % 60000) // 1000:02d}" if dur else ""
        media_refs = [f"(视频, 时长 {dur_str}) {master}"]
    else:
        media_refs = ["(无媒体)"]

    yymmdd = to_yymmdd(publish_ms)
    safe = f"{yymmdd}-{sanitize(title)}"
    out_md = dedup(out_dir / f"{safe}.md")
    source_url = f"https://www.xiaohongshu.com/explore/{note_id}"

    fm = ["---"]
    fm.append(f"title: {yml_escape(title)}")
    fm.append(f"publish_time: {publish_iso}")
    fm.append(f"category: {CATEGORY}")
    fm.append(f"source_url: {source_url}")
    fm.append(f"uid: {note_id}")
    fm.append(f"author: {yml_escape(author)}")
    if author_id:
        fm.append(f"author_id: {author_id}")
    fm.append(f'media_type: {"video" if is_video else ("image" if image_list else "mixed")}')
    fm.append("transcript_available: false")
    if fld(likes) is not None:
        fm.append(f"likes: {_parse_count(likes)}")
    if fld(comments) is not None:
        fm.append(f"comments: {_parse_count(comments)}")
    if fld(collects) is not None:
        fm.append(f"favorites: {_parse_count(collects)}")
    if tag_list:
        fm.append(
            "tags: ["
            + ", ".join(yml_escape(t) for t in tag_list if fld(t))
            + "]"
        )
    fm.append(f"source: {SOURCE}")
    fm.append(f"created: {datetime.now(TZ).strftime('%Y-%m-%dT%H:%M:%S')}")
    fm.append(f"note_id: {note_id}")
    fm.append('status: ocr_disabled')  # 2026-07-15: 用户关闭 xhs OCR
    if ip_loc:
        fm.append(f"ip_location: {yml_escape(ip_loc)}")
    fm.append("---")

    ip_prefix = f"{ip_loc} · " if ip_loc else ""
    body_media = "\n\n".join(media_refs) if media_refs else "(无媒体)"
    body = f"""

## 描述

{ip_prefix}{yml_escape(desc) or "(无)"}

## 媒体

{body_media}
"""
    out_md.write_text("\n".join(fm) + "\n" + body, encoding="utf-8")

    cache_d = cache_load()
    cache_d.setdefault(PLATFORM, []).append(note_id)
    cache_save(cache_d)

    _append_log(
        platform=PLATFORM,
        uid=note_id,
        md_abs_path=str(out_md),
        blogger=blogger,
        title=title,
        transcribed_by_mac=False,
    )

    log(f"  → {out_md.name}")
    print(f"BLOGGER_OK  1 条 ok (note_id={note_id[:12]})")


if __name__ == "__main__":
    main()
