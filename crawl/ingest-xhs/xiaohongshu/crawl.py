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
fetch_xhs_v2.py - opencli 方案抓小红书博主主页笔记
  - 走副 profile (dy2s6y2k) Chrome 登录态
  - 列表: opencli xiaohongshu user --limit 10
  - 单条: opencli browser open + eval __INITIAL_STATE__.note.noteDetailMap
  - 拿到: time(真实发布ms), desc, imageList(urlDefault+urlPre+width+height), video.masterUrl, interactInfo
  - frontmatter v1.4 schema; status: ocring
  - 缓存 .subscription-crawl-cache.json (按平台去重)
  - 写 fetch.log 给 VM subscription-expert 消费
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
import shutil
import time
import hashlib
import urllib.request
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

# scripts/ 加入 path (fetch_log, transcribe_local 在此目录)
_SKILL_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_SKILL_DIR / "scripts"))

from common.fetch_log import append_fetch_log as _append_log, _detect_share
from common.transcribe import load_config
from common.paths import media_dir, notes_dir
# 2026-07-15 用户设计变更: xhs "只爬原文档, OCR 和总结都关闭掉了"
# run_ocr/write_feishu 暂保留 import (不影响代码, 防止冷删意外回归), 调用已注释.
from ocr import run_ocr, write_feishu  # noqa: F401  # OCR 已关闭 (用户指令 2026-07-15)
from common.util import (sanitize, to_yymmdd, yml_escape, dedup,
    fld, _parse_count, run_opencli)
# 2026-08-25: 统一缓存到VM（与 common-flow/crawl.py 一致），Mac不再维护本地cache
from common.publish_vault import _load_state as cache_load, _save_state as cache_save

TZ = timezone(timedelta(hours=8))
PLATFORM = "xiaohongshu"
CATEGORY = "xhs"
SOURCE = "opencli"
OPENCLI_PROFILE = os.environ.get("OPENCLI_PROFILE", "dy2s6y2k")
BROWSER_SESSION = "xhs_main"

SHARE = _detect_share()


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


LIMIT = _get_limit()


def log(m):
    print(f"  {m}", flush=True)


def fail(m):
    print(f"FAIL  {m}", flush=True)
    sys.exit(1)




# 列表提取 JS 模板: 抽博主主页网格里 /user/profile/<UID>/<id>?xsec_token=... 链接
# (替代坏掉的 opencli xiaohongshu user 子命令 —— XHS 改版后该命令误报 AUTH_REQUIRED;
#  v2026-07-08: 主页网格有 2 个 <a>:
#    - 隐藏的 /explore/<id> (display:none, 没 xsec)
#    - 真实的 .cover.mask, 带 /user/profile/<UID>/<id>?xsec_token=...&xsec_source=pc_user
#  必须抽后者, 否则拿不到 xsec_token, 详情页会 300031 风控。
#  排序靠 note_id 前 8 hex (MongoDB ObjectID 时间戳), 与 publish_time 一致。)
LIST_JS_TMPL = """(function(){
  var UID="__UID__";
  var links=document.querySelectorAll('a.cover.mask[href*="/user/profile/"]');
  var seen={};var uniq=[];
  for(var i=0;i<links.length;i++){
    var h=links[i].getAttribute('href')||'';
    if(h.indexOf('/user/profile/'+UID+'/')<0)continue;
    var p=h.indexOf('/user/profile/'+UID+'/');
    var rest=h.substring(p+('/user/profile/'+UID+'/').length);
    var noteId=rest.split('?')[0]||'';
    var qt=rest.indexOf('xsec_token=');
    var xsec=qt>=0?rest.substring(qt+'xsec_token='.length).split('&')[0]:'';
    if(noteId&&xsec)uniq.push({id:noteId,xsec:decodeURIComponent(xsec)});
  }
  return JSON.stringify(uniq);
})()"""


def _note_id_ts(note_id):
    """MongoDB ObjectID 前 4 字节 = Unix 秒 (XHS 创建时间)
    返回 (ts_int, dt_str_ymdhm)。失败返回 (0, '')。
    XHS note id 是 24 hex 字符串, 前 8 hex 转 int 即 ts。
    """
    if not note_id or len(note_id) < 8:
        return 0, ""
    try:
        ts = int(note_id[:8], 16)
        from datetime import datetime
        dt = datetime.fromtimestamp(ts).strftime("%y%m%d-%H:%M")
        return ts, dt
    except Exception:
        return 0, ""


def fetch_user_notes(user_id_or_url, limit=LIMIT):
    """走 browser open 主页 + 滚动抽网格 id + 按 ObjectID 时间戳排序, 取最新 LIMIT 条。

    2026-07-08 重构:
    - XHS 改版后主页链接不再带 xsec_token, 也不再有发布时间显示
    - 改用 note_id 前 8 hex (MongoDB ObjectID) 转 Unix 秒, 该 ts 与 publish_time 几乎一致
    - 滚动 1-2 次拿到 ~30-60 个 id 就够 LIMIT=10, 不再过度滚动(避免限流)
    - 详情 URL 必须带 xsec_token: /explore/<id>?xsec_token=<xsec>&xsec_source=pc_user
      (无 xsec → 风控 300031; /search_result/<id> → 风控 300017, 均不可用)
    """
    if str(user_id_or_url).startswith("http"):
        user_id = str(user_id_or_url).rstrip("/").split("/")[-1]
    else:
        user_id = str(user_id_or_url)
    profile_url = f"https://www.xiaohongshu.com/user/profile/{user_id}"

    def _one_pass():
        """开主页 + 温和滚动 1-2 次, 返回 {id: xsec} dict 去重。"""
        run_opencli(["browser", BROWSER_SESSION, "open", profile_url], timeout=30)
        time.sleep(5)
        seen = {}
        prev_total = -1
        for i in range(3):  # 最多 3 次, 通常 1-2 次够
            run_opencli(
                ["browser", BROWSER_SESSION, "eval",
                 "(function(){window.scrollTo(0,document.body.scrollHeight);return 'ok';})()"],
                timeout=20,
            )
            time.sleep(3.5)
            js = LIST_JS_TMPL.replace("__UID__", user_id)
            out = run_opencli(["browser", BROWSER_SESSION, "eval", js], timeout=30)
            if out:
                try:
                    cur = json.loads(
                        re.sub(r"\n\s*Update available.*$", "", out, flags=re.DOTALL).strip()
                    )
                except Exception:
                    cur = []
            else:
                cur = []
            if not isinstance(cur, list):
                cur = []
            for o in cur:
                if isinstance(o, dict):
                    nid = o.get("id"); xs = o.get("xsec")
                    if nid and xs:
                        seen[nid] = xs
            total = len(seen)
            log(f"  滚动 {i+1}: 本轮 {len(cur)} 条, 累计 {total} 条")
            # 够 LIMIT 就停(给 limit 加 50% 余量防滚动不够多)
            if limit and total >= int(limit * 1.5):
                break
            if total == prev_total:
                break  # 不再增长就停
            prev_total = total
        return seen

    # 首轮; 若被限流(拿到极少), 歇一会重开重试一次
    seen = _one_pass()
    if len(seen) < 3:
        log("  首轮疑似被限流, 歇 3min 后重开重试")
        time.sleep(180)  # XHS 限流冷却约需数分钟, 12s 远远不够
        seen2 = _one_pass()
        if len(seen2) > len(seen):
            seen = seen2

    # 按 ObjectID 时间戳降序排序(等价于按 publish_time 倒序), 保留 xsec_token 给详情页
    items = sorted(seen.items(), key=lambda kv: _note_id_ts(kv[0]), reverse=True)
    if limit:
        items = items[:limit]
    log(f"  主页共 {len(seen)} 条 id, 按 ts 降序取前 {len(items)} 条")
    notes = []
    for nid, xsec in items:
        ts, dt = _note_id_ts(nid)
        # 详情 URL 必须带 xsec_token, 否则风控 300031 (XHS 改版后硬要求)
        notes.append({
            "id": nid,
            "url": f"https://www.xiaohongshu.com/explore/{nid}?xsec_token={xsec}&xsec_source=pc_user",
            "ts": ts,
            "xsec": xsec,
        })
    return notes


# 详情提取 JS: 轮询等 noteDetailMap 内容就绪(带 xsec_token 的详情页才加载得出)
DETAIL_JS = """(async function(){
  for(var i=0;i<24;i++){
    var s=window.__INITIAL_STATE__;
    if(s&&s.note&&s.note.noteDetailMap){
      var ks=Object.keys(s.note.noteDetailMap);
      if(ks.length){
        var n=s.note.noteDetailMap[ks[0]].note;
        if(n&&((n.desc||'').length>0||(n.imageList&&n.imageList.length>0)||(n.video&&n.video.media)))break;
      }
    }
    await new Promise(r=>setTimeout(r,500));
  }
  var s=window.__INITIAL_STATE__;
  if(!s||!s.note||!s.note.noteDetailMap)return JSON.stringify({err:'no_state'});
  var ks=Object.keys(s.note.noteDetailMap);
  if(!ks.length)return JSON.stringify({err:'no_note'});
  var n=s.note.noteDetailMap[ks[0]].note;
  if(!n)return JSON.stringify({err:'no_inner'});
  var v=n.video&&n.video.media&&n.video.media.stream&&n.video.media.stream.h264;
  var v0=v&&v[0];
  return JSON.stringify({
    time:n.time,lastUpdateTime:n.lastUpdateTime,type:n.type,title:n.title,desc:n.desc,ipLocation:n.ipLocation,
    tagList:(n.tagList||[]).map(function(t){return t.name;}),
    imageList:(n.imageList||[]).map(function(i){return {urlDefault:i.urlDefault,urlPre:i.urlPre,width:i.width,height:i.height};}),
    video:v0?{masterUrl:v0.masterUrl,backupUrls:v0.backupUrls,duration:v0.videoDuration||v0.duration,width:v0.width,height:v0.height,format:v0.format,size:v0.size}:null,
    interact:n.interactInfo,author:n.user&&n.user.nickname,authorId:n.user&&n.user.userId
  });
})()"""


def fetch_note_detail(feed_url):
    """拿单条笔记完整字段: time, desc, imageList, video, interactInfo"""
    out = run_opencli(
        ["browser", BROWSER_SESSION, "open", feed_url], timeout=30
    )
    if not out:
        return None

    out = run_opencli(["browser", BROWSER_SESSION, "eval", DETAIL_JS], timeout=30)
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
    """下载图片到 cache_root/media/，返回相对 out_dir 的路径(供 md 引用)"""
    if not url:
        return None
    vault_media = media_dir().resolve()
    vault_media.mkdir(parents=True, exist_ok=True)
    # 先用 urllib.request 试下载（公开 URL）
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.xiaohongshu.com/"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
    except Exception as primary_err:
        # Bug fix (2026-07-23): 删除 curl+主 Chrome cookie fallback
        # 原因: (1) 主 Chrome Cookies SQLite 被进程锁, curl 读不到; 
        #       (2) 违反 memory v11 铁律"绝不碰主 Chrome Profile 1";
        #       (3) XHS urlDefault 是公开 CDN URL, urllib 失败通常是网络问题而非缺 cookie.
        # 改为 urllib 重试 + 更好 headers
        import time
        for attempt in range(1, 3):
            try:
                time.sleep(2 * attempt)
                req2 = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Referer": "https://www.xiaohongshu.com/",
                        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    },
                )
                with urllib.request.urlopen(req2, timeout=45) as resp2:
                    data = resp2.read()
                break
            except Exception:
                if attempt == 2:
                    raise primary_err
        else:
            raise primary_err
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
    dst = vault_media / f"{md5}{ext}"
    if not dst.exists():
        dst.write_bytes(data)
    try:
        rel = os.path.relpath(dst, out_dir if out_dir else notes_dir())
        if rel.startswith("..") and not out_dir:
            rel = str(dst)
        return rel
    except Exception:
        return str(dst)
def write_md(out_md, fm_lines, body):
    md = "\n".join(fm_lines) + "\n" + body
    out_md.write_text(md, encoding="utf-8")




def cleanup_browser():
    try:
        subprocess.run(
            [_OPENCLI_BIN, "--profile", OPENCLI_PROFILE, "browser", BROWSER_SESSION, "close"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        pass


def main():
    if len(sys.argv) < 3:
        print("usage: fetch_xhs_v2.py <blogger_name> <user_id_or_url> [out_dir]", file=sys.stderr)
        sys.exit(1)
    blogger_name = sys.argv[1]
    user_id = sys.argv[2]
    out_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else (notes_dir() / PLATFORM / blogger_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"博主 [{blogger_name}] {user_id}")

    notes = fetch_user_notes(user_id, LIMIT)
    if not notes:
        fail(f"博主 {blogger_name} 主页拉取失败")
    log(f"主页: {len(notes)} 条笔记")

    cache = cache_load().get(PLATFORM, [])
    cache_set = set(cache)

    ok_count = 0
    skip_count = 0
    try:
        for note in notes:
            note_id = note.get("id", "")
            feed_url = note.get("url", "")
            title_meta = note.get("title", "(无标题)")
            if not note_id or not feed_url:
                continue
            if note_id in cache_set:
                log(f"[{note_id[:12]}] cached, 跳过")
                skip_count += 1
                continue

            detail = fetch_note_detail(feed_url)
            if not detail:
                log(f"[{note_id[:12]}] detail fail, 跳过")
                continue

            time.sleep(2)

            publish_ms = detail.get("time") or 0
            publish_iso = (
                datetime.fromtimestamp(publish_ms / 1000, TZ).strftime("%Y-%m-%dT%H:%M:%S")
                if publish_ms
                else datetime.now(TZ).strftime("%Y-%m-%dT%H:%M:%S")
            )
            title = fld(detail.get("title")) or title_meta
            desc = fld(detail.get("desc")) or ""
            interact = detail.get("interact") or {}
            author = fld(detail.get("author")) or blogger_name
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
                    url = img.get("urlDefault") or img.get("urlPre")
                    if not url:
                        continue
                    w, h = img.get("width"), img.get("height")
                    rel = download_to_cache_media(url, out_dir)
                    if rel:
                        alt = f"img_{i:02d}"
                        if w and h:
                            alt = f"{alt}|{w}x{h}"
                        media_refs.append(f"![{alt}]({rel})")
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
            fm.append(f"likes: {_parse_count(likes)}")
            fm.append(f"comments: {_parse_count(comments)}")
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
            # 2026-07-15 OCR 已关闭 (用户指令), 不再写 status: ocring
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
            write_md(out_md, fm, body)

            # 2026-07-15 OCR 已关闭 (用户指令 "只爬原文档, ocr和总结都关闭掉了")
            # 原: run_ocr(out_md, log)  # 调 xhs_ocr_rapid.sh + common/feishu.py
            # 现在: 直接写 md → pipeline 推 hot doc, 不做 OCR, 也不写飞书多维表格.

            cache_set.add(note_id)
            ok_count += 1
            log(f"  → {out_md.name}")

            _append_log(
                platform=PLATFORM,
                uid=note_id,
                md_abs_path=str(out_md),
                blogger=blogger_name,
                title=title,
                # 2026-07-15 OCR 已关闭 — transcribed_by_mac=False 表示"未转录",
                # 这里改为 True 反映"故意没做转录", 而不是"待转录".
                transcribed_by_mac=True,  # OCR 已关闭 (用户指令)
            )
    finally:
        cleanup_browser()

    cache_d = cache_load()
    cache_d[PLATFORM] = list(cache_set)
    cache_save(cache_d)

    print(f"BLOGGER_OK  {ok_count} 条 ok, {skip_count} 条 skip (cached)")


if __name__ == "__main__":
    main()
