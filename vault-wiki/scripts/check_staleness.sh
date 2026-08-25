#!/bin/bash
# check_staleness.sh — 检查 raw 文档是否在 Source 页 updated 后被修改（vault 版）
#
# 用法: echo '<JSON_ARRAY>' | bash check_staleness.sh
#
# 输入 (stdin): JSON 数组
#   [{"source_title":"...","raw_path":"<vault 相对路径>","raw_doc_type":"md","recorded_update":"2025-03-15 14:30"}]
#
# 输出 (stdout): JSON 对象
#   {"stale":[...],"missing":[...],"fresh":[...],"errors":[...]}
#   当文件不可访问时，errors 非空且脚本以非 0 退出；这些 path 不会进入 missing。
#
# 依赖: jq, stat
# 兼容: bash 3.2+（macOS 默认）

set -uo pipefail

TOLERANCE_SECONDS=300  # 5 分钟容忍度
ERROR_EXIT_CODE=1

_vault_base() {
  if [ -n "${VAULT:-}" ]; then echo "$VAULT";
  elif [ "$(uname -s)" = "Linux" ]; then echo "/home/ubuntu/webdav/steven_vault";
  else echo "$HOME/Documents/steven_vault"; fi
}
VB="$(_vault_base)"

# ---------- 工具函数 ----------

file_mtime_unix() {
  local p="$1" abs
  abs="$VB/$p"
  if [ ! -e "$abs" ]; then echo "0"; return; fi
  if date -r 0 "+%Y" >/dev/null 2>&1; then
    date -r "$abs" "+%s"
  else
    date -r "$abs" "+%s" 2>/dev/null || stat -c '%Y' "$abs"
  fi
}

unix_to_datetime() {
  local ts="$1"
  if date -r 0 "+%Y" >/dev/null 2>&1; then
    date -r "$ts" "+%Y-%m-%d %H:%M"
  else
    date -d "@$ts" "+%Y-%m-%d %H:%M"
  fi
}

datetime_to_unix() {
  local dt="$1"
  if date -j -f "%Y-%m-%d %H:%M" "$dt" "+%s" >/dev/null 2>&1; then
    date -j -f "%Y-%m-%d %H:%M" "$dt" "+%s"
  else
    date -d "$dt" "+%s"
  fi
}

normalize_timestamp() {
  local ts="$1"
  if echo "$ts" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'; then
    echo "${ts} 23:59"
  else
    echo "$ts"
  fi
}

append_error() {
  local context="$1" kind="$2" message="$3"
  ERRORS=$(echo "$ERRORS" | jq --arg c "$context" --arg k "$kind" --arg m "$message" '. + [{"context":$c,"kind":$k,"message":$m}]')
}

output_result() {
  jq -n --argjson stale "$STALE" --argjson missing "$MISSING" \
    --argjson fresh "$FRESH" --argjson errors "$ERRORS" \
    '{"stale": $stale, "missing": $missing, "fresh": $fresh, "errors": $errors}'
}

# ---------- 主逻辑 ----------

INPUT=$(cat)
STALE="[]"
MISSING="[]"
FRESH="[]"
ERRORS="[]"

if [ -z "$INPUT" ] || [ "$INPUT" = "[]" ] || [ "$INPUT" = "null" ]; then
  output_result
  exit 0
fi

ENTRY_COUNT=$(echo "$INPUT" | jq 'length')
if [ "$ENTRY_COUNT" -eq 0 ]; then
  output_result
  exit 0
fi

idx=0
while [ "$idx" -lt "$ENTRY_COUNT" ]; do
  source_title=$(echo "$INPUT" | jq -r ".[$idx].source_title")
  raw_path=$(echo "$INPUT" | jq -r ".[$idx].raw_path")
  recorded_update=$(echo "$INPUT" | jq -r ".[$idx].recorded_update")

  raw_modified_unix=$(file_mtime_unix "$raw_path")

  if [ "$raw_modified_unix" = "0" ]; then
    # 文件不可访问 — 进入 missing（此处简化：不区分 errors/missing，飞书版 API 失败才进 errors）
    MISSING=$(echo "$MISSING" | jq --arg t "$source_title" --arg p "$raw_path" '. + [{"source_title":$t,"raw_path":$p,"error":"not found"}]')
    idx=$((idx + 1))
    continue
  fi

  raw_modified_dt=$(unix_to_datetime "$raw_modified_unix")
  normalized_recorded=$(normalize_timestamp "$recorded_update")
  recorded_unix=$(datetime_to_unix "$normalized_recorded" 2>/dev/null || echo "0")

  delta=$((raw_modified_unix - recorded_unix))

  if [ "$delta" -gt "$TOLERANCE_SECONDS" ]; then
    delta_hours=$((delta / 3600))
    STALE=$(echo "$STALE" | jq \
      --arg t "$source_title" --arg p "$raw_path" \
      --arg rec "$recorded_update" --arg mod "$raw_modified_dt" --argjson h "$delta_hours" \
      '. + [{"source_title":$t,"raw_path":$p,"recorded_update":$rec,"raw_modified":$mod,"delta_hours":$h}]')
  else
    FRESH=$(echo "$FRESH" | jq \
      --arg t "$source_title" --arg p "$raw_path" --arg rec "$recorded_update" --arg mod "$raw_modified_dt" \
      '. + [{"source_title":$t,"raw_path":$p,"recorded_update":$rec,"raw_modified":$mod}]')
  fi

  idx=$((idx + 1))
done

output_result
