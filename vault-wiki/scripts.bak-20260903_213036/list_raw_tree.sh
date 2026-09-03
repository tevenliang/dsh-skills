#!/bin/bash
# list_raw_tree.sh — 递归枚举 raw 引用目录的整棵子树，输出扁平 JSON（vault 版）
#
# 用于「reference 模式」：raw 层引用一棵已有 vault 目录树时，下游（ingest/import/lint）
# 用本脚本实时枚举原树，感知原树后续新增的子目录/文档，而非依赖 INDEX.md 静态快照。
#
# 用法 (全部走环境变量):
#   RAW_PATH="<原目录 vault 相对路径>" [MAX_DEPTH=8] [ROOT_PATH=raw] bash list_raw_tree.sh
#
# 入参:
#   RAW_PATH     递归起点目录的 vault 相对路径（必填）
#   MAX_DEPTH    最大递归深度，默认 8（防环/防超深）
#   ROOT_PATH    输出 path 的根前缀，默认 "raw"
#
# 输出 (stdout): JSON 对象
#   {"nodes":[{"path","title","is_container","depth","rel_path"}, ...],"errors":[...]}
#   当目录不可访问时，errors 非空且脚本以非 0 退出；
#   下游必须据此区分「真的无子节点」与「访问失败」，不得把失败当作「无新增」。

set -uo pipefail

RAW_PATH="${RAW_PATH:?需要 RAW_PATH（递归起点目录的 vault 相对路径）}"
MAX_DEPTH="${MAX_DEPTH:-8}"
ROOT_PATH="${ROOT_PATH:-raw}"

_vault_base() {
  if [ -n "${VAULT:-}" ]; then echo "$VAULT";
  elif [ "$(uname -s)" = "Linux" ]; then echo "/home/ubuntu/webdav/steven_vault";
  else echo "$HOME/Documents/steven_vault"; fi
}
VB="$(_vault_base)"
ABS="$VB/$RAW_PATH"

ERROR_EXIT_CODE=1
NODES="[]"
ERRORS="[]"

if [ ! -d "$ABS" ]; then
  ERRORS=$(echo "$ERRORS" | jq --arg m "目录不存在: $RAW_PATH" '. + [{"context":"input","kind":"not_found","message":$m}]')
  echo "$(jq -n --argjson nodes "$NODES" --argjson errors "$ERRORS" '{"nodes":$nodes,"errors":$errors}')"
  exit "$ERROR_EXIT_CODE"
fi

# 计算相对根的深度偏移
root_depth=$(echo "$RAW_PATH" | tr '/' '\n' | wc -l | tr -d ' ')

walk() {
  local dir_abs="$1" dir_rel="$2" depth="$3"
  if [ "$depth" -gt "$MAX_DEPTH" ]; then
    ERRORS=$(echo "$ERRORS" | jq --arg p "$dir_rel" --arg m "达到 MAX_DEPTH=$MAX_DEPTH，停止下探" '. + [{"context":$p,"kind":"max_depth","message":$m}]')
    return
  fi
  # 子目录（容器）
  local child
  for child in "$dir_abs"/*/; do
    [ -d "$child" ] || continue
    local name; name="$(basename "$child")"
    local crel="${dir_rel}/${name}"
    NODES=$(echo "$NODES" | jq --arg p "$crel" --arg t "$name" --argjson d "$depth" \
      '. + [{"path":$p,"title":$t,"is_container":true,"depth":$d,"rel_path":$p}]')
    walk "$child" "$crel" $((depth + 1))
  done
  # .md 叶子
  local f
  for f in "$dir_abs"/*.md; do
    [ -f "$f" ] || continue
    local name; name="$(basename "$f")"
    local rel="${dir_rel}/${name}"
    NODES=$(echo "$NODES" | jq --arg p "$rel" --arg t "$name" --arg rel "$rel" --argjson d "$depth" \
      '. + [{"path":$p,"title":$t,"is_container":false,"depth":$d,"rel_path":$rel}]')
  done
}

walk "$ABS" "$ROOT_PATH" "$root_depth"

echo "$(jq -n --argjson nodes "$NODES" --argjson errors "$ERRORS" '{"nodes":$nodes,"errors":$errors}')"
if [ "$(echo "$ERRORS" | jq 'length')" -ne 0 ]; then
  exit "$ERROR_EXIT_CODE"
fi
