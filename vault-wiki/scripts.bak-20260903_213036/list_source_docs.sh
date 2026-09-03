#!/bin/bash
# list_source_docs.sh — 枚举源目录的一级直接子项（仅 .md，过滤子目录）（vault 版）
#
# 用于 digest 工作流：获取用户指定的目录下一层所有 .md 文档（仅一层，不递归），
# 输出扁平 JSON 列表。
#
# 用法：
#   SOURCE_PATH="<源目录 vault 相对路径>" bash list_source_docs.sh
#
# 入参（环境变量）：
#   SOURCE_PATH   源目录的 vault 相对路径（必填）
#
# 输出（stdout）：JSON 对象
#   {
#     "files": [
#       {"rel_path": "24_阅读思考/my-wiki/wiki/sources/某主题/a.md", "title": "文章标题"}
#     ],
#     "errors": [...]
#   }
#
# 行为：
#   - 仅列出直接子项（一级）
#   - 仅返回 .md 文件（过滤子目录）
#   - 目录不可访问时 errors 非空，脚本以非 0 退出

set -uo pipefail

SOURCE_PATH="${SOURCE_PATH:?需要 SOURCE_PATH（源目录的 vault 相对路径）}"

_vault_base() {
  if [ -n "${VAULT:-}" ]; then echo "$VAULT";
  elif [ "$(uname -s)" = "Linux" ]; then echo "/home/ubuntu/webdav/steven_vault";
  else echo "$HOME/Documents/steven_vault"; fi
}
VB="$(_vault_base)"
ABS="$VB/$SOURCE_PATH"

ERROR_EXIT_CODE=1
NODES="[]"
ERRORS="[]"

if [ ! -d "$ABS" ]; then
  ERRORS=$(echo "$ERRORS" | jq --arg m "目录不存在: $SOURCE_PATH" '. + [{"context":"input","kind":"not_found","message":$m}]')
  echo "$(jq -n --argjson files "$NODES" --argjson errors "$ERRORS" '{"files":$files,"errors":$errors}')"
  exit "$ERROR_EXIT_CODE"
fi

for f in "$ABS"/*.md; do
  [ -f "$f" ] || continue
  title="$(head -1 "$f" | sed -E 's/^#?[[:space:]]*//')"
  [ -z "$title" ] && title="$(basename "$f" .md)"
  NODES=$(echo "$NODES" | jq --arg p "$SOURCE_PATH/$(basename "$f")" --arg t "$title" '. + [{"rel_path":$p,"title":$t}]')
done

echo "$(jq -n --argjson files "$NODES" --argjson errors "$ERRORS" '{"files":$files,"errors":$errors}')"
if [ "$(echo "$ERRORS" | jq 'length')" -ne 0 ]; then
  exit "$ERROR_EXIT_CODE"
fi
