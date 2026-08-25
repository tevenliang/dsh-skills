#!/usr/bin/env bash
# monitor.sh — 实时看 4 平台抓取进度
# 用法: bash monitor.sh [--loop 30]   # 默认 30s 刷新
# 单次: bash monitor.sh once
# 退出 watch: q / Ctrl-C

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SUB="$(python3 -c "import sys;sys.path.insert(0,'$SCRIPT_DIR');import paths;print(paths.notes_dir())" 2>/dev/null || echo "$HOME/Library/Caches/subscription-crawl/notes")"
CACHE="$(python3 -c "import sys;sys.path.insert(0,'$SCRIPT_DIR');import paths;print(paths.cache_file())" 2>/dev/null || echo "$HOME/Library/Caches/subscription-crawl/state/.subscription-crawl-cache.json")"
LOG="$(python3 -c "import sys;sys.path.insert(0,'$SCRIPT_DIR');import paths;print(paths.sub_log())" 2>/dev/null || echo "$HOME/Library/Caches/subscription-crawl/logs/subscription_log.md")"

LOOP=30
if [ "${1:-}" = "--loop" ] && [ -n "${2:-}" ]; then LOOP="$2"; fi

snapshot() {
  clear 2>/dev/null || true
  echo "═══════════════════════════════════════════════════════════════"
  echo "  subscription 4 平台抓取 monitor  $(date '+%Y-%m-%d %H:%M:%S')"
  echo "═══════════════════════════════════════════════════════════════"
  echo ""

  # 1. 后台任务状态
  echo "【后台任务】"
  RUN_PID=$(pgrep -f "run_all.sh --crawl" 2>/dev/null | head -1)
  if [ -n "$RUN_PID" ]; then
    RUNTIME=$(ps -p "$RUN_PID" -o etime= 2>/dev/null | tr -d ' ')
    CPU=$(ps -p "$RUN_PID" -o %cpu= 2>/dev/null | tr -d ' ')
    echo "  ▶ run_all.sh --crawl  PID=$RUN_PID  跑 $RUNTIME  CPU=${CPU}%"
  else
    echo "  — 无 run_all.sh 任务"
  fi
  OPENCLI_PID=$(pgrep -f "opencli" 2>/dev/null | head -1)
  if [ -n "$OPENCLI_PID" ]; then
    OCLI_ETIME=$(ps -p "$OPENCLI_PID" -o etime= 2>/dev/null | tr -d ' ')
    echo "  ▶ opencli 进程 PID=$OPENCLI_PID  跑 $OCLI_ETIME"
  fi
  XHS_PID=$(lsof -i :18060 2>/dev/null | grep LISTEN | awk '{print $2}' | head -1)
  if [ -n "$XHS_PID" ]; then
    XHS_ETIME=$(ps -p "$XHS_PID" -o etime= 2>/dev/null | tr -d ' ')
    echo "  ▶ xiaohongshu-mcp  PID=$XHS_PID  跑 $XHS_ETIME  端口 18060"
  fi
  echo ""

  # 2. 4 平台 cache 状态
  echo "【4 平台 cache 状态】"
  if [ -f "$CACHE" ]; then
    python3 -c "
import json
d = json.loads(open('$CACHE').read())
plats = ['bilibili', 'douyin', 'xiaohongshu', 'wechat']
labels = {'bilibili':'B 站  ', 'douyin':'抖音  ', 'xiaohongshu':'小红书', 'wechat':'微信  '}
for p in plats:
    n = len(d.get(p, []))
    bar = '█' * (n // 5) if n > 0 else ''
    print(f'  {labels.get(p,p):6} {n:>4}  {bar}')
" 2>/dev/null
  else
    echo "  cache 文件不存在"
  fi
  echo ""

  # 3. 磁盘文件数
  echo "【磁盘文件数】"
  for p in bilibili douyin xiaohongshu wechat; do
    n=$(find "$SUB/$p" -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
    sub=$(find "$SUB/$p" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
    echo "  $p  共 $n 个 md, $sub 个博主目录"
  done
  echo ""

  # 4. 最新抓取 (subscription_log.md 倒数 5 行)
  echo "【最近 5 条台账】"
  if [ -f "$LOG" ]; then
    grep -E "^- " "$LOG" 2>/dev/null | tail -5 | sed 's/^/  /'
  fi
  echo ""

  # 5. 当前最新文件
  echo "【最新 5 个抓取文件】"
  find "$SUB/bilibili" "$SUB/douyin" "$SUB/xiaohongshu" "$SUB/wechat" -name "*.md" 2>/dev/null \
    -newer "$LOG" 2>/dev/null | head -5 | sed 's|^|  |'
  # fallback: 按修改时间排
  if [ "$(find "$SUB/bilibili" "$SUB/douyin" "$SUB/xiaohongshu" "$SUB/wechat" -name "*.md" -newer "$LOG" 2>/dev/null | wc -l)" = "0" ]; then
    find "$SUB/bilibili" "$SUB/douyin" "$SUB/xiaohongshu" "$SUB/wechat" -name "*.md" 2>/dev/null \
      -mmin -60 | sort -k1,2 | head -5 | sed 's|^|  |'
  fi
  echo ""
  echo "═══════════════════════════════════════════════════════════════"
  echo "  Ctrl-C 退出 / 刷新间隔 ${LOOP}s"
}

# 单次模式
if [ "${1:-}" = "once" ]; then
  snapshot
  exit 0
fi

# loop 模式
trap 'echo ""; echo "退出 monitor"; exit 0' INT TERM
while true; do
  snapshot
  sleep "$LOOP"
done
