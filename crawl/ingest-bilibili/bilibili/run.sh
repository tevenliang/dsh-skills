#!/usr/bin/env bash
# bilibili/fetch.sh — B站博主视频抓取独立入口 (v2, 支持 USE_VM 开关)
# 用法: bash bilibili/fetch.sh
set -u
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$SKILL_DIR/scripts/lib.sh"

LOG="$LOG_DIR/crawl_$(date +%m%d_%H%M%S)_bili.log"

# 读取 USE_VM 开关
USE_VM=$(python3 -c "import yaml,sys; c=yaml.safe_load(open('$SKILL_DIR/config.yaml')); print('true' if c.get('USE_VM') else 'false')" 2>/dev/null || echo "true")
export USE_VM
echo "[$(date '+%H:%M:%S')] USE_VM=$USE_VM" | tee -a "$LOG"

extract_bili_mid() { echo "$1" | sed -E "s/.*space\.bilibili\.com\/([0-9]+).*/\1/"; }

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

echo "[$(date '+%H:%M:%S')] 开始: B站" | tee "$LOG"
echo "日志: $LOG" | tee -a "$LOG"

# 跨博主并发度: 环境变量 CONCURRENCY > config.parallel_authors > 默认 4
PARALLEL_AUTHORS=$(python3 -c "import yaml; c=yaml.safe_load(open('$SKILL_DIR/config.yaml')); print(c.get('parallel_authors', 4))" 2>/dev/null || echo 4)
CONCURRENCY=${CONCURRENCY:-$PARALLEL_AUTHORS}
CONCURRENCY=${CONCURRENCY:-4}
[[ "$CONCURRENCY" -ge 1 ]] 2>/dev/null || CONCURRENCY=4
echo "[$(date '+%H:%M:%S')] 跨博主并发度 CONCURRENCY=$CONCURRENCY" | tee -a "$LOG"

_prep_bloggers_fd bilibili
line="" url="" name="" mid="" idx=0
pids=()
while IFS= read -r line <&9; do
  [[ -z "$line" ]] && continue
  IFS='|' read -r url name <<< "$line"
  [[ -z "$url" ]] && continue
  idx=$((idx+1))
  mid=$(extract_bili_mid "$url")
  if [[ -z "$mid" ]]; then
    echo "[跳过] $name (无mid)" | tee -a "$LOG"
    continue
  fi
  echo "[$(date '+%H:%M:%S')] [$idx] 启动 B站 $name mid=$mid (并发 ${#pids[@]}/$CONCURRENCY)" | tee -a "$LOG"
  bili_dir=$(ensure_blogger_dir bilibili "$name")
  SKILL_DIR="$SKILL_DIR" USE_VM="$USE_VM" python3 "$SKILL_DIR/bilibili/crawl.py" "$mid" "$name" "$bili_dir" >> "$LOG" 2>&1 &
  pids+=($!)
  # 达到并发上限, 等最旧的一个完成后继续 (FIFO 背压)
  if [[ ${#pids[@]} -ge $CONCURRENCY ]]; then
    wait "${pids[0]}"
    pids=("${pids[@]:1}")
  fi
  sleep 1
done
# 等剩余全部完成
for p in "${pids[@]:-}"; do
  [[ -n "$p" ]] && wait "$p"
done
_close_bloggers_fd

echo "=== B站完成 $(date '+%H:%M:%S') ===" | tee -a "$LOG"
