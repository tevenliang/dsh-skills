#!/usr/bin/env bash
# douyin/fetch.sh — 抖音博主视频抓取独立入口 (支持 USE_VM 开关)
# 用法: bash douyin/fetch.sh
set -u
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$SKILL_DIR/scripts/lib.sh"

LOG="$LOG_DIR/crawl_$(date +%m%d_%H%M%S)_dy.log"

# 读取 USE_VM 开关
USE_VM=$(python3 -c "import yaml,sys; c=yaml.safe_load(open('$SKILL_DIR/config.yaml')); print('true' if c.get('USE_VM') else 'false')" 2>/dev/null || echo "true")
export USE_VM
echo "[$(date '+%H:%M:%S')] USE_VM=$USE_VM" | tee -a "$LOG"

extract_dy_secuid() { echo "$1" | sed -E "s/.*douyin\.com\/user\/([A-Za-z0-9_-]+).*/\1/"; }

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

echo "[$(date '+%H:%M:%S')] 开始: 抖音" | tee "$LOG"
echo "日志: $LOG" | tee -a "$LOG"

_prep_bloggers_fd douyin
line="" url="" name="" su="" idx=0
while IFS= read -r line <&9; do
  [[ -z "$line" ]] && continue
  IFS='|' read -r url name <<< "$line"
  [[ -z "$url" ]] && continue
  idx=$((idx+1))
  su=$(extract_dy_secuid "$url")
  if [[ -z "$su" ]]; then
    echo "[跳过] $name (无sec_uid)" | tee -a "$LOG"
    continue
  fi
  echo "[$(date '+%H:%M:%S')] [$idx] 抖音 $name" | tee -a "$LOG"
  dy_dir=$(ensure_blogger_dir douyin "$name")
  USE_VM="$USE_VM" \
    python3 "$SKILL_DIR/douyin/crawl.py" "$su" "$name" "$dy_dir" >> "$LOG" 2>&1 || true
  sleep 5
done
_close_bloggers_fd

echo "=== 抖音完成 $(date '+%H:%M:%S') ===" | tee -a "$LOG"
