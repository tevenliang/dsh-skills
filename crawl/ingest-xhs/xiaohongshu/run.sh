#!/usr/bin/env bash
# xiaohongshu/fetch.sh — 小红书博主笔记抓取独立入口
# 用法: bash xiaohongshu/fetch.sh
set -u
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$SKILL_DIR/scripts/lib.sh"

LOG="$LOG_DIR/crawl_$(date +%m%d_%H%M%S)_xhs.log"

extract_xhs_uid() { echo "$1" | sed -E "s/.*user\/profile\/([0-9a-f]{20,}).*/\1/"; }

_prep_bloggers_fd() {
  local plat="$1"
  local tmp; tmp=$(mktemp)
  get_active_bloggers "$plat" > "$tmp" 2>/dev/null
  local count; count=$(wc -l < "$tmp" | tr -d ' ')
  echo "  共 ${count} 个博主" | tee -a "$LOG"
  exec 9<"$tmp"
  FD_TMP="$tmp"
}

_close_bloggers_fd() {
  exec 9<&- 2>/dev/null || true
  [[ -n "${FD_TMP:-}" && -e "$FD_TMP" ]] && rm -f "$FD_TMP"
}

echo "[$(date '+%H:%M:%S')] 开始: 小红书" | tee "$LOG"
echo "日志: $LOG" | tee -a "$LOG"

_prep_bloggers_fd xiaohongshu
line="" url="" name="" uid="" idx=0
while IFS= read -r line <&9; do
  [[ -z "$line" ]] && continue
  IFS='|' read -r url name <<< "$line"
  [[ -z "$url" ]] && continue
  idx=$((idx+1))
  uid=$(extract_xhs_uid "$url")
  if [[ -z "$uid" ]]; then
    echo "[跳过] $name (无uid)" | tee -a "$LOG"
    continue
  fi
  echo "[$(date '+%H:%M:%S')] [$idx] 小红书 $name uid=$uid" | tee -a "$LOG"
  # 心跳: 抓取前先 ping opencli doctor, 防止 MV3 Service Worker 休眠导致断连
  OPENCLI_BIN="${OPENCLI_BIN:-$HOME/.npm-global/bin/opencli}"
  "$OPENCLI_BIN" doctor >/dev/null 2>&1 || true
  python3 "$SKILL_DIR/xiaohongshu/crawl.py" "$name" "$uid" >> "$LOG" 2>&1 || true
  sleep 8
done
_close_bloggers_fd

echo "=== 小红书完成 $(date '+%H:%M:%S') ===" | tee -a "$LOG"
