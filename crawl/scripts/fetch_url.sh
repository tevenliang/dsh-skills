#!/usr/bin/env bash
# fetch_url.sh - 单条 URL 抓取(3 平台: B 站 / 抖音 / 小红书)
# 用法: subscription-crawl <url> [--blogger <name>] [--inbox]
# 输出: 默认 subscription/<platform>/<blogger>/; --inbox 则落 00_inbox/
# 缓存: 走 .subscription-crawl-cache.json
# 日志: 自动追加 subscription_log.md

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib.sh"
export OMNICRAWL_SCRIPT_DIR="$SCRIPT_DIR"

GROQ_CRED="$HOME/.agents/credentials/ominicrawl/groq.json"
GROQ_KEY=""
if [ -f "$GROQ_CRED" ]; then
  GROQ_KEY=$(python3 -c "import json; print(json.load(open('$GROQ_CRED'))['api_key'])" 2>/dev/null || true)
fi
if [ -z "$GROQ_KEY" ]; then
  warn "未找到 Groq key,无字幕视频无法转写,仅落元数据"
fi
export GROQ_KEY

# --- 超时守护: 5 分钟强制退出
SCRIPT_START=$(date +%s)
MAX_DURATION=300
watchdog() {
  while true; do
    sleep 30
    elapsed=$(($(date +%s) - SCRIPT_START))
    if [ $elapsed -gt $MAX_DURATION ]; then
      echo "❌ 脚本运行超过 ${MAX_DURATION}s，强制退出" >&2
      pkill -f "opencli.*daemon" 2>/dev/null || true
      exit 124
    fi
  done
}
watchdog &
WATCHDOG_PID=$!
trap "kill $WATCHDOG_PID 2>/dev/null || true" EXIT

# --- daemon 健康检查
check_daemon() {
  local pid=$(pgrep -f "daemon.js" 2>/dev/null | head -1)
  if [ -z "$pid" ]; then
    echo "[daemon] not running, starting..."
    nohup opencli daemon > /dev/null 2>&1 &
    sleep 3
  elif ! timeout 5 opencli doctor 2>&1 | grep -qE "OK|ready|connected"; then
    echo "[daemon] not responding, restarting..."
    pkill -f "daemon.js" 2>/dev/null; sleep 1
    nohup opencli daemon > /dev/null 2>&1 &
    sleep 3
  fi
}
check_daemon

URL="${1:-}"
shift || true
BLOGGER_HINT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --blogger) BLOGGER_HINT="${2:-}"; shift 2 ;;
    --inbox) INBOX_MODE=1; SUBSCRIPTION_INBOX=1; shift ;;
    --no-cache) NO_CACHE=1 ;;
    *) shift ;;
  esac
done

if [ -z "$URL" ]; then
  echo "用法: subscription-crawl <url> [--blogger <name>] [--inbox]" >&2
  exit 1
fi

PLATFORM=""
case "$URL" in
  *bilibili.com*|*b23.tv*)         PLATFORM="bilibili" ;;
  *xiaohongshu.com*|*xhslink.com*) PLATFORM="xiaohongshu" ;;
  *douyin.com*|*iesdouyin.com*)    PLATFORM="douyin" ;;
  *mp.weixin.qq.com*|*view.inews.qq.com*) PLATFORM="wechat" ;;
esac
if [ -z "$PLATFORM" ]; then
  echo "❌ 无法识别 URL 平台: $URL" >&2
  exit 1
fi

case "$PLATFORM" in
  bilibili)   CATEGORY="bilibili" ;;
  xiaohongshu) CATEGORY="xhs" ;;
  douyin)     CATEGORY="douyin" ;;
  wechat)     CATEGORY="wx" ;;
esac
SOURCE="opencli"
export OPENCLI_PROFILE=dy2s6y2k
export PLATFORM CATEGORY SOURCE CACHE_FILE URL

BLOGGER="${BLOGGER_HINT:-unknown}"

# SUBSCRIPTION_INBOX=1 → 落 vault 00_inbox/ 平铺
if [ "${SUBSCRIPTION_INBOX:-}" = "1" ]; then
  INBOX_MODE=1
  INBOX_ROOT="$INBOX_DIR"
  mkdir -p "$INBOX_ROOT"
  OUT_DIR="$INBOX_ROOT"
  log "inbox 模式: → $INBOX_ROOT"
else
  INBOX_MODE=0
  INBOX_ROOT=""
  OUT_DIR=$(ensure_blogger_dir "$PLATFORM" "$BLOGGER")
fi

log "单条抓取: platform=$PLATFORM url=$URL blogger=$BLOGGER${INBOX_MODE:+ [inbox]}"

export OUT_DIR BLOGGER INBOX_MODE INBOX_ROOT

set +e
RESULT=$(python3 - <<'PYMAIN'
import os, sys, json, subprocess, tempfile, shutil, time, re, hashlib
from pathlib import Path
from datetime import datetime

# 飞书 Watchlist 文档(取代本地 watchlist.md)读取支持
_SCRIPT_DIR = Path(os.environ.get('OMNICRAWL_SCRIPT_DIR', '.'))
sys.path.insert(0, str(_SCRIPT_DIR.parent / 'common'))
try:
    from feishu_watchlist import get_watchlist_markdown
except Exception:
    get_watchlist_markdown = None

OUT_DIR = os.environ['OUT_DIR']
BLOGGER = os.environ['BLOGGER']
PLATFORM = os.environ['PLATFORM']
CATEGORY = os.environ['CATEGORY']
SOURCE = os.environ['SOURCE']
GROQ_KEY = os.environ.get('GROQ_KEY', '')
URL = os.environ['URL']
CACHE_FILE = os.environ['CACHE_FILE']
SCRIPT_DIR = os.environ.get('OMNICRAWL_SCRIPT_DIR', '.')
INBOX_MODE = os.environ.get('INBOX_MODE', '0') == '1'
INBOX_ROOT = os.environ.get('INBOX_ROOT', '')

def log(m): print(f'  {m}', flush=True)
def fail(m): print(f'FAIL  {m}', flush=True); sys.exit(1)

def to_yymmdd(val):
    try:
        r = subprocess.run(
            ['bash', '-c', f'source "{SCRIPT_DIR}/lib.sh" && to_yymmdd "$1"', '_', str(val)],
            capture_output=True, text=True, timeout=5
        )
        out = r.stdout.strip()
        return out if out else datetime.now().strftime('%y%m%d')
    except Exception:
        return datetime.now().strftime('%y%m%d')

def sanitize(s):
    s = s.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_')
    s = s.replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_')
    s = s.replace('\n', ' ').replace('\r', ' ')
    s = re.sub(r'[._]+$', '', s)
    return s[:60].strip()

def dedup(path):
    if not os.path.exists(path): return path
    base, ext = os.path.splitext(path)
    if not ext: base, ext = path, ''
    i = 2
    while i < 100:
        cand = f'{base}_{i}{ext}'
        if not os.path.exists(cand): return cand
        i += 1
    return path

def yml_escape(s):
    if s is None: return ''
    s = str(s)
    # 先把换行/制表/回车合并成单空格(避免 YAML "..." 跨行不合法)
    s = re.sub(r'\s+', ' ', s)
    if any(c in s for c in [':', '"', '#']) or s.strip() != s:
        s = s.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{s}"'
    return s

def cache_load():
    p = Path(CACHE_FILE)
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}

def cache_add(uid):
    p = Path(CACHE_FILE)
    d = cache_load()
    d.setdefault(PLATFORM, [])
    if uid not in d[PLATFORM]:
        d[PLATFORM].append(uid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')

def cache_has(uid):
    return uid in cache_load().get(PLATFORM, [])

def fld(v):
    return v if (v is not None and (not isinstance(v, str) or v.strip())) else None

def _parse_count(v):
    """点赞/评论/收藏/时长数转 int。支持中文单位: '1.5万'/'1.2w'/'3500'/'10+'/'0'。
    无法解析返回 0(不抛异常, 避免单条抓取中断)。与 common/util.py 逻辑一致。"""
    if v is None:
        return 0
    s = str(v).strip().replace("+", "").replace(" ", "")
    if not s:
        return 0
    mult = 1
    if s[-1] in "万Ww":
        mult = 10000
        s = s[:-1]
    elif s[-1] in "亿Yy":
        mult = 100000000
        s = s[:-1]
    try:
        return int(float(s) * mult)
    except Exception:
        return 0

def transcribe_audio(mp4_path, groq_key):
    if not groq_key:
        return '', ''
    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, 'v.wav')
        subprocess.run(['ffmpeg', '-y', '-i', mp4_path, '-ar', '16000', '-ac', '1', wav],
                       capture_output=True, timeout=120)
        if not os.path.exists(wav):
            return '', ''
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                '-of', 'csv=p=0', wav], capture_output=True, text=True, timeout=30)
        try: total = float(probe.stdout.strip())
        except Exception: total = 0
        wav_size = os.path.getsize(wav)
        if wav_size < 20 * 1024 * 1024 or total <= 600:
            chunks = [(0, total, wav)]
        else:
            chunks = []
            t = 0; idx = 0
            while t < total:
                t_end = min(t + 600, total)
                cp = os.path.join(tmp, f'c{idx:03d}.wav')
                subprocess.run(['ffmpeg', '-y', '-i', wav, '-ss', str(t), '-to', str(t_end),
                                '-ar', '16000', '-ac', '1', cp], capture_output=True, timeout=60)
                chunks.append((t, t_end, cp)); t = t_end; idx += 1
        all_text = []
        for (t0, t1, cp) in chunks:
            cr = subprocess.run(['curl', '-s', '--max-time', '300',
                                 '-X', 'POST', 'https://api.groq.com/openai/v1/audio/transcriptions',
                                 '-H', f'Authorization: Bearer {groq_key}',
                                 '-F', 'file=@' + cp,
                                 '-F', 'model=whisper-large-v3',
                                 '-F', 'response_format=verbose_json',
                                 '-F', 'language=zh'],
                                capture_output=True, text=True, timeout=320)
            try:
                cdata = json.loads(cr.stdout)
                for s in cdata.get('segments', []):
                    t = s.get('text', '').strip()
                    if t: all_text.append(t)
            except Exception as e:
                log(f'  groq chunk fail: {e}')
        return ' '.join(all_text), 'Whisper'

now = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

if PLATFORM == 'bilibili':
    m = re.search(r'(BV[A-Za-z0-9]+)', URL)
    if not m:
        fail(f'B 站 URL 提取不到 bvid: {URL}')
    bvid = m.group(1)
    log(f'bvid = {bvid}')
    if cache_has(bvid):
        log(f'[{bvid}] 已在 cache,跳过')
        print('BLOGGER_OK  1 条 cached 跳过')
        sys.exit(0)

    _env = os.environ.copy()
    _env['OPENCLI_PROFILE'] = os.environ.get('OPENCLI_PROFILE', 'dy2s6y2k')
    vr = subprocess.run(['opencli', 'bilibili', 'video', bvid, '-f', 'json'],
                        capture_output=True, text=True, timeout=60, env=_env)
    description, pub_time, dur, author = ('',) * 4
    likes, comments, favorites, play = ('',) * 4
    try:
        vdata = json.loads(vr.stdout)
        if isinstance(vdata, list):
            for f in vdata:
                fn, val = f.get('field', ''), f.get('value', '')
                if fn == 'description': description = val
                elif fn == 'publish_time': pub_time = val
                elif fn == 'duration': dur = val
                elif fn == 'author': author = val
                elif fn == 'like': likes = val
                elif fn == 'reply': comments = val
                elif fn == 'favorite': favorites = val
                elif fn == 'view': play = val
    except Exception as e:
        fail(f'video detail parse fail: {e}')

    title = ''
    try:
        sr2 = subprocess.run(['opencli', 'bilibili', 'search', bvid, '--limit', '1', '-f', 'json'],
                             capture_output=True, text=True, timeout=30, env=_env)
        sdata2 = json.loads(sr2.stdout)
        if isinstance(sdata2, list) and sdata2 and sdata2[0].get('title'):
            title = sdata2[0]['title']
    except Exception:
        pass
    if not title and description:
        title = description.strip().split('\n')[0].strip()[:80]
    if not title:
        title = f'B站视频 {bvid}'
    title = title[:80]
    log(f'title = {title}')

    transcript, transcribe_source, has_cc = '', '', False
    sr = subprocess.run(['opencli', 'bilibili', 'subtitle', bvid, '-f', 'json'],
                        capture_output=True, text=True, timeout=60, env=_env)
    try:
        sdata = json.loads(sr.stdout)
        if isinstance(sdata, list) and len(sdata) > 0:
            has_cc = True
            lines = [seg.get('content', '').strip() for seg in sdata if seg.get('content', '').strip()]
            transcript = ' '.join(lines)
            transcribe_source = 'CC 字幕'
            log(f'  CC 字幕 {len(sdata)} 段')
    except Exception as e:
        log(f'  subtitle fail: {e}')
    if not has_cc and GROQ_KEY:
        log('  无 CC,走 Whisper')
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(['opencli', 'bilibili', 'download', bvid, '--output', tmp, '-f', 'json'],
                           capture_output=True, text=True, timeout=180, env=_env)
            mp4 = None
            for root, _, fns in os.walk(tmp):
                for fn in fns:
                    if re.search(r'\.(mp4|m4v)$', fn, re.I):
                        mp4 = os.path.join(root, fn); break
                if mp4: break
            if mp4:
                transcript, transcribe_source = transcribe_audio(mp4, GROQ_KEY)
                log(f'  Whisper 完成')

    body = transcript if transcript else '(无转录内容)'
    source_url = f'https://www.bilibili.com/video/{bvid}'

    mid = ''
    _am = re.search(r'"?(.+?)\s*\(mid:\s*(\d+)\)"?', author)
    if _am:
        author_name, mid = _am.group(1).strip(), _am.group(2)
    else:
        author_name = author.strip().strip('"')

    dur_sec = 0
    dm = re.search(r'\((\d+)\s*s\)', dur)
    if dm: dur_sec = int(dm.group(1))
    else:
        dm2 = re.search(r'(\d+)\s*s', dur)
        if dm2: dur_sec = int(dm2.group(1))

    publish_time_val = pub_time
    if publish_time_val and 'T' not in publish_time_val:
        if re.match(r'^\d{4}-\d{2}-\d{2}$', publish_time_val):
            publish_time_val = publish_time_val + 'T00:00:00'
        else:
            m3 = re.match(r'^(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})', publish_time_val)
            if m3:
                publish_time_val = f"{m3.group(1)}T{int(m3.group(2)):02d}:{m3.group(3)}:00"
    if not publish_time_val: publish_time_val = now

    yymmdd = to_yymmdd(pub_time)
    safe = f'{yymmdd}-{sanitize(title)}'
    out_md = dedup(os.path.join(OUT_DIR, f'{safe}.md'))

    fm_lines = ['---']
    fm_lines.append(f'title: {yml_escape(title)}')
    fm_lines.append(f'publish_time: {publish_time_val}')
    fm_lines.append(f'category: {CATEGORY}')
    fm_lines.append(f'source_url: {source_url}')
    fm_lines.append(f'uid: {bvid}')
    fm_lines.append(f'author: {yml_escape(author_name or "unknown")}')
    fm_lines.append(f'author_id: {mid}')
    fm_lines.append(f'media_type: video')
    if dur_sec: fm_lines.append(f'duration: {dur_sec}')
    fm_lines.append(f'transcript_source: {yml_escape(transcribe_source or "")}')
    fm_lines.append(f'transcript_available: {str(bool(transcript)).lower()}')
    if fld(likes) is not None: fm_lines.append(f'likes: {_parse_count(likes)}')
    if fld(comments) is not None: fm_lines.append(f'comments: {_parse_count(comments)}')
    if fld(favorites) is not None: fm_lines.append(f'favorites: {_parse_count(favorites)}')
    fm_lines.append('tags: []')
    fm_lines.append(f'source: {SOURCE}')
    fm_lines.append(f'created: {now}')
    fm_lines.append(f'bvid: {bvid}')
    if mid: fm_lines.append(f'mid: {mid}')
    # inbox 单条落盘，根据 transcript 设置 status
    if transcript:
        fm_lines.append('status: ["transcribing", "summarizing", "abstracting"]')
    else:
        fm_lines.append('status: ["summarizing", "abstracting"]')
    fm_lines.append('---')
    md = '\n'.join(fm_lines) + f"""

## 描述

{description or '(无描述)'}

## 转录(来源: {transcribe_source or '无'})

{body}
"""
    with open(out_md, 'w', encoding='utf-8') as f:
        f.write(md)
    cache_add(bvid)
    log(f'  → {os.path.basename(out_md)} (cached)')
    print(f'BLOGGER_OK  1 条 ok (bvid={bvid})')

elif PLATFORM == 'xiaohongshu':
    # v2 方案: 调 fetch_url_xhs_v2.py (xiaohongshu-mcp, 无需 xsec_token 强制要求)
    v2_script = os.path.join(os.path.dirname(SCRIPT_DIR), 'xiaohongshu', 'fetch_url.py')
    if not os.path.exists(v2_script):
        fail(f'fetch_url_xhs_v2.py 不存在: {v2_script}')
    blogger_for_search = BLOGGER
    r = subprocess.run(
        [sys.executable, v2_script, URL, blogger_for_search, OUT_DIR],
        capture_output=True, text=True, timeout=180
    )
    if r.returncode != 0:
        fail(f'fetch_url_xhs_v2 fail (rc={r.returncode}): {r.stderr.strip() or r.stdout.strip()[:200]}')
    sys.stdout.write(r.stdout)
    if 'BLOGGER_OK' not in r.stdout:
        fail(f'fetch_url_xhs_v2 no BLOGGER_OK: {r.stdout[:200]}')
    sys.exit(0)
elif PLATFORM == 'douyin':
    _env = os.environ.copy()
    _env['OPENCLI_PROFILE'] = os.environ.get('OPENCLI_PROFILE', 'dy2s6y2k')

    # --- 1. 解析 short link → aweme_id ---
    if 'v.douyin.com' in URL or '/share/video/' in URL:
        log('  解析抖音短链...')
        rr = subprocess.run(['curl', '-sI', '-L', '--max-time', '15', URL],
                            capture_output=True, text=True, timeout=20)
        locs = re.findall(r'(?im)^location:\s*(\S+)', rr.stdout)
        real_url = ''
        for loc in locs:
            m_loc = re.search(r'https?://www\.douyin\.com/video/(\d{15,})', loc)
            if m_loc:
                real_url = f'https://www.douyin.com/video/{m_loc.group(1)}'
                break
        if not real_url:
            fail(f'抖音短链解析失败: {URL}')
        log(f'  短链 → {real_url}')
        URL = real_url
        os.environ['URL'] = URL

    m = re.search(r'/video/(\d{15,})', URL)
    if not m:
        fail(f'抖音 URL 提取不到 aweme_id: {URL}')
    aweme_id = m.group(1)
    log(f'aweme_id = {aweme_id}')

    if cache_has(aweme_id):
        log(f'[{aweme_id}] 已在 cache,跳过')
        print('BLOGGER_OK  1 条 cached 跳过')
        sys.exit(0)

    # --- 2. 查找 sec_uid: 精确匹配 watchlist > 模糊匹配 > blogger name ---
    # watchlist 3 列表 (博主 / 分类 / url), 平台由 ## 标题承担
    # 数据源: 飞书文档 "Watchlist 关注博主清单"(本地 watchlist.md 已废弃)
    sec_uid = None
    blogger_name = BLOGGER

    def parse_douyin_rows(wt_text):
        # watchlist 3 列表 (博主 / 分类 / url), 平台由 ## 标题承担
        # 跟踪 ## 标题, 提取 platform==douyin 的 (name, url), 默认全开
        import re as _re
        rows = []
        current_plat = None
        in_table = False
        for ln in wt_text.splitlines():
            s = ln.strip()
            if s.startswith('## '):
                in_table = False
                m_h = _re.search(r'\(([\w-]+)\)', s)
                current_plat = m_h.group(1).lower() if m_h else None
                continue
            if not s.startswith('|'):
                in_table = False
                continue
            cells = [c.strip() for c in s.strip('|').split('|')]
            if not cells:
                continue
            if all(_re.match(r'^-+$', c) for c in cells if c):
                in_table = True
                continue
            if '博主' in s and 'url' in s.lower():
                in_table = True
                continue
            in_table = True
            if len(cells) < 3:
                continue
            try:
                name, category, url = cells[:3]
            except ValueError:
                continue
            if current_plat is None or 'douyin' not in current_plat:
                continue
            if not url:
                continue
            rows.append((name, url))
        return rows
    wt_rows = parse_douyin_rows(get_watchlist_markdown()) if get_watchlist_markdown else []
    for nm, u in wt_rows:
        # 精确匹配 blogger name
        if BLOGGER != 'unknown' and nm == BLOGGER:
            sm = re.search(r'/user/([A-Za-z0-9_-]+)', u)
            if sm:
                sec_uid = sm.group(1)
                blogger_name = nm
                log(f'  watchlist 精确命中: [{nm}]')
                break
        # 精确匹配 URL 里的 sec_uid
        sm = re.search(r'/user/([A-Za-z0-9_-]+)', u)
        if sm and sm.group(1) in URL:
            sec_uid = sm.group(1)
            blogger_name = nm
            log(f'  watchlist URL 命中: [{nm}]')

    # 模糊匹配: watchlist 博主名 包含/被包含 blogger_name
    if not sec_uid and blogger_name and blogger_name != 'unknown':
        for nm2, u2 in wt_rows:
            if nm2 in blogger_name or blogger_name in nm2:
                sm2 = re.search(r'/user/([A-Za-z0-9_-]+)', u2)
                if sm2:
                    sec_uid = sm2.group(1)
                    blogger_name = nm2
                    log(f'  watchlist 模糊命中: [{nm2}]')
                    break

    if not sec_uid:
        fail(f'无法获取 sec_uid, 请在飞书 Watchlist 文档(订阅Subscription 节点下)的 ## 抖音 (douyin) 表格加一行: | <博主名> | <分类> | https://www.douyin.com/user/<sec_uid> |\n  (sec_uid 在作者主页 URL 里找, /user/ 后面的字符串)')

    # --- 3. user-videos 拉列表 → 找目标视频 ---
    r = subprocess.run(['opencli', 'douyin', 'user-videos', sec_uid, '--limit', '20',
                        '--with_comments', 'false', '-f', 'json'],
                       capture_output=True, text=True, timeout=120, env=_env)
    try:
        raw = r.stdout
        start = raw.index('[')
        end = raw.rindex(']') + 1
        data = json.loads(raw[start:end])
    except Exception as e:
        fail(f'user-videos parse fail: {e}')
    if not isinstance(data, list):
        fail(f'user-videos unexpected payload: {type(data)}')

    v = next((x for x in data if str(x.get('aweme_id', '')) == aweme_id), None)
    if not v:
        fail(f'aweme_id {aweme_id} 不在博主 [{blogger_name}] 最近 20 条中')

    title = v.get('title', '(无标题)')
    play_url = str(v.get('play_url', ''))
    duration = v.get('duration', 0)
    digg = v.get('digg_count', '')
    create_time = v.get('create_time', '')
    source_url = f'https://www.douyin.com/video/{aweme_id}'
    log(f'title = {title[:50]}')

    transcript, transcribe_source = '', ''
    with tempfile.TemporaryDirectory() as tmp:
        if play_url and play_url.startswith('http'):
            mp4 = os.path.join(tmp, 'v.mp4')
            subprocess.run(['curl', '-sL', '--max-time', '200',
                            '-H', 'Referer: https://www.douyin.com/',
                            '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                            play_url, '-o', mp4],
                           capture_output=True, timeout=220)
            sz = os.path.getsize(mp4) if os.path.exists(mp4) else 0
            if sz > 10000 and GROQ_KEY:
                transcript, transcribe_source = transcribe_audio(mp4, GROQ_KEY)
                log(f'  Whisper 完成 ({len(transcript)} 字)')
            elif sz > 10000:
                log(f'  视频下载完成({sz//1024//1024}MB), 无 Groq Key')
            else:
                log(f'  视频下载失败')

    publish_time_val = create_time or now
    yymmdd = to_yymmdd(create_time)
    safe = f'{yymmdd}-{sanitize(title)}'

    # 单条: 始终落 notes/<platform>/ (不带博主子目录, 博主信息存 frontmatter)
    out_dir = str(Path(os.environ['NOTES_DIR']) / PLATFORM)

    out_md = dedup(os.path.join(out_dir, f'{safe}.md'))
    fm_lines = ['---']
    fm_lines.append(f'title: {yml_escape(title)}')
    fm_lines.append(f'publish_time: {publish_time_val}')
    fm_lines.append(f'category: {CATEGORY}')
    fm_lines.append(f'source_url: {source_url}')
    fm_lines.append(f'uid: {aweme_id}')
    fm_lines.append(f'author: {yml_escape(blogger_name)}')
    fm_lines.append(f'author_id: {sec_uid}')
    fm_lines.append(f'media_type: video')
    if fld(duration): fm_lines.append(f'duration: {_parse_count(duration)}')
    fm_lines.append(f'transcript_source: {yml_escape(transcribe_source)}')
    fm_lines.append(f'transcript_available: {str(bool(transcript)).lower()}')
    if fld(digg) is not None: fm_lines.append(f'likes: {_parse_count(digg)}')
    fm_lines.append(f'favorites: "-"')
    fm_lines.append(f'tags: []')
    fm_lines.append(f'source: {SOURCE}')
    fm_lines.append(f'created: {now}')
    fm_lines.append(f'aweme_id: {aweme_id}')
    fm_lines.append(f'sec_uid: {sec_uid}')
    # inbox 单条落盘，根据 transcript 设置 status
    if transcript:
        fm_lines.append('status: ["transcribing", "summarizing", "abstracting"]')
    else:
        fm_lines.append('status: ["summarizing", "abstracting"]')
    fm_lines.append('---')
    md = '\n'.join(fm_lines) + f"""

## 描述

{title}

## 转录(来源: {transcribe_source or '无'})

{transcript or '(无转录内容)'}
"""
    os.makedirs(os.path.dirname(out_md), exist_ok=True)
    with open(out_md, 'w', encoding='utf-8') as f:
        f.write(md)
    cache_add(aweme_id)
    log(f'  → {os.path.basename(out_md)}')
    print(f'BLOGGER_OK  1 条 ok (aweme_id={aweme_id})')
elif PLATFORM == 'wechat':
    _env = os.environ.copy()
    _env['OPENCLI_PROFILE'] = os.environ.get('OPENCLI_PROFILE', 'dy2s6y2k')
    NOTE_URL = URL

    wx_uid = ''
    mm = re.search(r'/s/([a-zA-Z0-9_-]{16,})', NOTE_URL)
    if mm: wx_uid = mm.group(1)
    log(f'wechat uid = {wx_uid}')

    if cache_has(wx_uid):
        log(f'[{wx_uid[:12]}] 已在 cache,跳过')
        print('BLOGGER_OK  1 条 cached 跳过')
        sys.exit(0)

    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run(
            ['opencli', 'weixin', 'download', '--url', NOTE_URL,
             '--output', tmp, '--site-session', 'ephemeral', '-f', 'json'],
            capture_output=True, text=True, timeout=90, env=_env
        )
        try:
            jdata = json.loads(r.stdout)
            if isinstance(jdata, list): jdata = jdata[0]
        except Exception as e:
            fail(f'weixin download parse fail: {e}')

        title = jdata.get('title', '微信公众号文章')
        author = jdata.get('author', BLOGGER)
        pub_time_raw = jdata.get('publish_time', '')
        saved_md = jdata.get('saved', '')
        log(f'title = {title[:50]}, author = {author}')

        if not saved_md or not os.path.exists(saved_md):
            fail(f'weixin download 未返回有效文件: {saved_md}')

        vault_media = Path(os.environ['MEDIA_DIR'])
        os.makedirs(vault_media, exist_ok=True)

        img_dir = os.path.join(os.path.dirname(saved_md), 'images')
        raw_md = Path(saved_md).read_text(encoding='utf-8')

        def replace_img(m):
            fname = m.group(1)
            src = os.path.join(img_dir, fname)
            if not os.path.exists(src):
                return m.group(0)
            md5h = hashlib.md5(open(src, 'rb').read()).hexdigest()
            ext = os.path.splitext(fname)[1].lower()
            if ext in ('.other',):
                ext = '.png'
            dst = vault_media / f'{md5h}{ext}'
            if not dst.exists():
                shutil.copy2(src, dst)
            rel = os.path.relpath(dst, OUT_DIR)
            # 按实际像素尺寸: ≤300px 按原尺寸, >300px 缩到 800px 宽
            try:
                from PIL import Image
                im = Image.open(str(dst))
                w, h = im.width, im.height
                size_suffix = f'|{w}' if w <= 300 else '|800'
            except Exception:
                size_suffix = '|400'
            return f'![[{rel}{size_suffix}]]'

        body = re.sub(r'!\[图片\]\(images/([^)]+)\)', replace_img, raw_md)

        publish_time_val = now
        if pub_time_raw:
            ptm = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})', pub_time_raw)
            if ptm:
                publish_time_val = f"{ptm.group(1)}-{int(ptm.group(2)):02d}-{int(ptm.group(3)):02d}T{int(ptm.group(4)):02d}:{ptm.group(5)}:00"
            else:
                pm2 = re.match(r'(\d{4})-(\d{2})-(\d{2})', pub_time_raw)
                if pm2:
                    publish_time_val = pub_time_raw + 'T00:00:00'

        yymmdd = publish_time_val[5:7] + publish_time_val[8:10] if len(publish_time_val) >= 10 else datetime.now().strftime('%y%m%d')
        safe = f'{yymmdd}-{sanitize(title)}'
        out_md = dedup(os.path.join(OUT_DIR, f'{safe}.md'))
        os.makedirs(OUT_DIR, exist_ok=True)

        fm_lines = ['---']
        fm_lines.append(f'title: {yml_escape(title)}')
        fm_lines.append(f'publish_time: {publish_time_val}')
        fm_lines.append(f'category: wx')
        fm_lines.append(f'source_url: {NOTE_URL}')
        fm_lines.append(f'uid: {wx_uid}')
        fm_lines.append(f'author: {yml_escape(author)}')
        fm_lines.append(f'author_id: "-"')
        fm_lines.append(f'media_type: image')
        fm_lines.append('transcript_source: "-"')
        fm_lines.append('transcript_available: false')
        fm_lines.append('likes: "-"')
        fm_lines.append('comments: "-"')
        fm_lines.append('favorites: "-"')
        fm_lines.append('tags: []')
        fm_lines.append(f'source: {SOURCE}')
        fm_lines.append(f'created: {now}')
        fm_lines.append(f'wx_uid: {wx_uid}')
        # wechat 和 inbox 都需要总结
        fm_lines.append('status: ["summarizing", "abstracting"]')
        fm_lines.append('---')
        md = '\n'.join(fm_lines) + f"\n\n{body}\n"
        with open(out_md, 'w', encoding='utf-8') as f_out:
            f_out.write(md)
        cache_add(wx_uid)
        log(f'  → {os.path.basename(out_md)} (cached)')
        print(f'BLOGGER_OK  1 条 ok (wx_uid={wx_uid[:12]})')
)
set -e

if echo "$RESULT" | grep -q "^BLOGGER_OK"; then
  log "完成"
  SUMMARY=$(echo "$RESULT" | grep '^BLOGGER_OK' | sed 's/^BLOGGER_OK  //')
  log_append "$PLATFORM" "$BLOGGER" "单条 URL: $SUMMARY" "新增"
else
  warn "单条抓取失败"
  echo "  详情: $RESULT" >&2
  log_append "$PLATFORM" "$BLOGGER" "" "失败"
  exit 1
fi
