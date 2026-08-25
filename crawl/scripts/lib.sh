#!/usr/bin/env bash
# lib.sh - watchlist 抓取公共函数 + subscription 目录管理
# watchlist 现在是 3 列表(博主 / 分类 / url),按 ## 平台小节切分:
#   ## 抖音 (douyin)
#   | 博主 | 分类 | url |
#   | --- | --- | --- |
#   | 淘沙博士 | 财经-头部 | https://www.douyin.com/user/MS4w... |
# 公众号走 wewe-rss 不进 watchlist,本函数只处理三平台

set -euo pipefail

# ── 路径集中管理(脱离 steven_vault, 由 scripts/paths.py 解析) ──
SKILL_DIR="${SKILL_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

_resolve_sub_paths() {
  python3 - "$SKILL_DIR" <<'PY' 2>/dev/null || true
import sys, os
sys.path.insert(0, os.path.join(sys.argv[1], 'scripts'))
import paths
for k, v in [
    ("SUB_BASE", paths.notes_dir()),
    ("OUT_BASE", paths.notes_dir()),
    ("CACHE_FILE", paths.cache_file()),
    ("SUB_LOG", paths.sub_log()),
    ("MEDIA_DIR", paths.media_dir()),
    ("LOG_DIR", paths.logs_dir()),
    ("INBOX_DIR", paths.inbox_dir()),
    ("NOTES_DIR", paths.notes_dir()),
]:
    print(f'{k}={v}')
PY
}
eval "$(_resolve_sub_paths)"

# 兜底默认值(python 解析失败时使用)
PRJ="${HOME}/WorkBuddy/MyWorkSpace/project_crawl"
: "${SUB_BASE:=${PRJ}/notes}"
: "${OUT_BASE:=${PRJ}/notes}"
: "${CACHE_FILE:=${PRJ}/state/.subscription-crawl-cache.json}"
: "${SUB_LOG:=${PRJ}/logs/subscription_log.md}"
: "${MEDIA_DIR:=${PRJ}/media}"
: "${LOG_DIR:=${PRJ}/logs}"
: "${INBOX_DIR:=${PRJ}/notes/inbox}"
: "${NOTES_DIR:=${PRJ}/notes}"

# 导出供内嵌 python 子进程读取
export SUB_BASE CACHE_FILE SUB_LOG MEDIA_DIR LOG_DIR INBOX_DIR NOTES_DIR

# 确保目录存在
python3 - "$SKILL_DIR" <<'PY' 2>/dev/null || true
import sys, os
sys.path.insert(0, os.path.join(sys.argv[1], 'scripts'))
import paths
paths.ensure_dirs()
PY

TODAY=$(date +%Y-%m-%d)

# log
log()  { echo "[$(date +%H:%M:%S)] $*"; }
warn() { echo "⚠️  $*" >&2; }

# --- watchlist 解析 ---

# 旧版 list 解析(已废弃,只为兼容旧脚本)
get_active_section() {
  echo "get_active_section 已废弃,请用 get_active_bloggers" >&2
  return 1
}

# 解析 watchlist 列表形式,返回 "<url>|<name>" 行
# 数据来源: 飞书文档 "Watchlist 关注博主清单"(订阅Subscription 节点下),
# 本地 watchlist.md 已废弃(避免两处歧义)。解析逻辑不变。
get_active_bloggers() {
  # plat: bilibili / douyin / xiaohongshu
  # watchlist 3 列表(博主 / 分类 / url),平台由 ## 小节标题承担
  # 默认全开,没有'启用'列;公众号走 wewe-rss 不进 watchlist
  local plat="$1"
  local common_dir
  common_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../common" && pwd)"
  python3 - "$common_dir" "$plat" <<'PY' 2>/dev/null
import sys, re
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from feishu_watchlist import get_watchlist_markdown
plat_keyword = sys.argv[2]
text = get_watchlist_markdown()

# 跟踪 ## 标题识别当前小节平台 (## 抖音 (douyin) / ## B 站 (bilibili) / ## 小红书 (xiaohongshu))
current_plat = None
in_table = False
for line in text.splitlines():
    stripped = line.strip()
    if stripped.startswith('## '):
        in_table = False
        m = re.search(r'\(([\w-]+)\)', stripped)
        current_plat = m.group(1).lower() if m else None
        continue
    if not stripped.startswith('|'):
        in_table = False
        continue
    cells = [c.strip() for c in stripped.strip('|').split('|')]
    if not cells:
        continue
    if all(re.match(r'^-+$', c) for c in cells if c):
        in_table = True
        continue
    if '博主' in stripped and 'url' in stripped.lower():
        in_table = True
        continue
    in_table = True
    if len(cells) < 3:
        continue
    name, category, url = cells[:3]
    if current_plat is None or plat_keyword not in current_plat:
        continue
    if not url or not url.startswith(('http://', 'https://')):
        continue
    print(f'{url}|{name}')
PY
}

# --- 路径管理 ---

# 旧版:temp/<date>/<platform>
ensure_outdir() {
  local platform="$1"
  local dir="${OUT_BASE}/${TODAY}/${platform}"
  mkdir -p "$dir"
  echo "$dir"
}

# 新版:subscription/<platform>/<blogger_name>
ensure_blogger_dir() {
  local platform="$1"
  local name="$2"
  local safe
  safe=$(sanitize_name "$name")
  if [ -z "$safe" ]; then
    safe="unnamed"
  fi
  local dir="${SUB_BASE}/${platform}/${safe}"
  mkdir -p "$dir"
  echo "$dir"
}

# --- 文件名 / 文本处理 ---

# 安全文件名(去文件系统非法字符,限长)
sanitize_name() {
  echo "$1" | tr '/\\:*?"<>|' '_' | tr -d '\n' | head -c 60 | sed 's/[._-]*$//'
}

# 路径去重:若已存在,追加 _2/_3
dedup_path() {
  local path="$1"
  if [ ! -e "$path" ]; then
    echo "$path"
    return
  fi
  local base="${path%.*}"
  local ext="${path##*.}"
  if [ "$base" = "$path" ] || [ -z "$ext" ]; then
    # 无后缀
    local i=2
    while [ -e "${path}_${i}" ]; do
      i=$((i+1))
    done
    echo "${path}_${i}"
  else
    local i=2
    while [ -e "${base}_${i}.${ext}" ]; do
      i=$((i+1))
    done
    echo "${base}_${i}.${ext}"
  fi
}

# ISO 时间(本地时区)
now_iso() {
  python3 -c "from datetime import datetime; print(datetime.now().strftime('%Y-%m-%dT%H:%M:%S'))"
}

# --- 平台 uid 提取 ---

# B 站 URL → uid
extract_bili_uid() {
  echo "$1" | sed -nE 's|.*space\.bilibili\.com/([0-9]+).*|\1|p'
}

# 抖音 URL → sec_uid
extract_douyin_secuid() {
  echo "$1" | sed -nE 's|.*/user/([A-Za-z0-9_-]+).*|\1|p'
}

# --- 缓存机制 ---
# 已抓过的 uid 存在 $CACHE_FILE,二次抓取自动跳过
# 格式: { "bilibili": ["BVxxx", ...], "douyin": [...], "xiaohongshu": [...] }
# 手工清理:删掉某 uid 数组项,下次 subscription-crawl 会重新拉

# 读取整个 cache(json),返回空对象 if not exists
cache_load() {
  if [ -f "$CACHE_FILE" ]; then
    cat "$CACHE_FILE"
  else
    echo '{}'
  fi
}

# 检查某平台是否已处理该 uid,exit 0 = 已处理(跳过),exit 1 = 未处理
cache_has() {
  local platform="$1" uid="$2"
  cache_load | python3 -c "
import json, sys
d = json.load(sys.stdin)
sys.exit(0 if '$uid' in d.get('$platform', []) else 1)
" 2>/dev/null
}

# 写入一条 uid 到 cache(去重)
cache_add() {
  local platform="$1" uid="$2"
  python3 - "$CACHE_FILE" "$platform" "$uid" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
platform = sys.argv[2]
uid = sys.argv[3]
d = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
d.setdefault(platform, [])
if uid not in d[platform]:
    d[platform].append(uid)
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')
PY
}

# 统计 cache 数量
cache_count() {
  local platform="$1"
  cache_load | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(len(d.get('$platform', [])))
" 2>/dev/null
}

# 列出某平台所有已 cache 的 uid(每行一个,空行跳过)
cache_list() {
  local platform="$1"
  cache_load | python3 -c "
import json, sys
d = json.load(sys.stdin)
for u in d.get('$platform', []):
    print(u)
" 2>/dev/null
}


# --- 文件名 mmdd ---
# 时间字段 -> "mmdd" 字符串; 优先解析发布时间,失败 fallback 到今天
# 接受的格式: int unix ts (秒或毫秒) / 'YYYY-MM-DD HH:MM:SS' /
#            'YYYY-MM-DD' / 'YYYY-MM-DDTHH:MM:SS' / 'YYYY/MM/DD'
# 抖音拿不到发布时间时,调用方传空字符串,自动 fallback 到抓取日
to_yymmdd() {
  local val="$1"
  MMDD_VAL="$val" python3 -c "
import os
from datetime import datetime
v = (os.environ.get('MMDD_VAL') or '').strip()
now = datetime.now()
def fb(): print(now.strftime('%y%m%d'))
if not v: fb(); raise SystemExit
try:
    if v.isdigit():
        ts = int(v)
        if ts > 1e12: ts = ts / 1000
        print(datetime.fromtimestamp(ts).strftime('%y%m%d')); raise SystemExit
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%Y/%m/%d'):
        try:
            print(datetime.strptime(v, fmt).strftime('%y%m%d')); raise SystemExit
        except ValueError: pass
    fb()
except SystemExit: pass
except Exception: fb()
"
}

# --- subscription-crawl 抓取日志 ---
# 每次 fetch_*.sh 跑完, 自动追加到 $SUB_LOG(subscription_log.md)
# section 格式: "## YYYY-MM-DD HH:MM:SS subscription-crawl 全平台抓取" + 表格
# 距上次 section header > 5 分钟 → 新开 section;否则续写

log_start_session() {
  local now_epoch
  now_epoch=$(date +%s)
  local last_epoch=0
  if [ -f "$SUB_LOG" ]; then
    local last_ts
    last_ts=$(grep -E '^## [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}' "$SUB_LOG" 2>/dev/null | tail -1 | sed -E 's/^## ([0-9-]+ [0-9:]+).*/\1/')
    if [ -n "$last_ts" ]; then
      last_epoch=$(date -j -f "%Y-%m-%d %H:%M:%S" "$last_ts" "+%s" 2>/dev/null || echo 0)
    fi
  fi
  local diff=$((now_epoch - last_epoch))
  if [ "$diff" -gt 300 ] || [ "$last_epoch" = "0" ]; then
    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    {
      echo ""
      echo "## $ts subscription-crawl 全平台抓取"
      echo ""
      echo "| 平台 | 博主 | 摘要 | 状态 |"
      echo "| --- | --- | --- | --- |"
    } >> "$SUB_LOG"
  fi
}

log_append() {
  local platform="$1" blogger="$2" summary="$3" status="$4"
  log_start_session
  echo "| $platform | $blogger | $summary | $status |" >> "$SUB_LOG"
}

# ============================================================
# 文件名截断公共函数
# 规则: 中文原样保留, 英文保留, 总长度不超过 80 字符(不含 yymmdd- 前缀)
# ============================================================
_filename_title() {
    local title="$1"
    local max_len=80
    
    # 替换非法字符
    title=$(echo "$title" | sed \
        -e 's/\//_/g' \
        -e 's/\\/ _/g' \
        -e 's/:/_/g' \
        -e 's/\*/_/g' \
        -e 's/?/_/g' \
        -e 's/"/_/g' \
        -e 's/</_/g' \
        -e 's/>/_/g' \
        -e 's/|/_/g' \
        -e 's/\n/ /g' \
        -e 's/\r/ /g' \
        -e 's/  */ /g' \
        -e 's/^ *//; s/ *$//')
    
    # 按字符数截断(中文1字符=1,不按字节)
    if [ ${#title} -gt $max_len ]; then
        title="${title:0:$max_len}"
    fi
    
    # 去掉尾部可能的空格/标点
    title=$(echo "$title" | sed 's/[ _.,;:。，、；：.!！?？]*$//')
    echo "$title"
}
