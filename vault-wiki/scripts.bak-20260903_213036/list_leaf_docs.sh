#!/bin/bash
# list_leaf_docs.sh — 枚举源目录的一级直接叶子 md（不递归）
#
# 用法：
#   SOURCE_DIR="21_ai/openclaw" bash list_leaf_docs.sh
#
# 输出：JSON { "files": [{"rel_path","abs_path","title","size"}], "errors": [...] }

set -uo pipefail

SOURCE_DIR="${SOURCE_DIR:?需要 SOURCE_DIR（源目录 vault 相对路径）}"

_vault_base() {
  if [ -n "${VAULT:-}" ]; then echo "$VAULT";
  elif [ "$(uname -s)" = "Linux" ]; then echo "/home/ubuntu/webdav/steven_vault";
  else echo "$HOME/Documents/steven_vault"; fi
}
VB="$(_vault_base)"
ABS="$VB/$SOURCE_DIR"

NODES="[]"
ERRORS="[]"

if [ ! -d "$ABS" ]; then
  ERRORS=$(echo "$ERRORS" | jq --arg m "目录不存在: $SOURCE_DIR" \
    '. + [{"context":"input","kind":"not_found","message":$m}]')
  echo "$(jq -n --argjson files "$NODES" --argjson errors "$ERRORS" \
    '{"files":$files,"errors":$errors}')"
  exit 1
fi

for f in "$ABS"/*.md; do
  [ -f "$f" ] || continue
  # 提取标题：优先取第一个 # 标题，其次用文件名
  title="$(head -1 "$f" | sed -E 's/^#?[[:space:]]*//; s/[[:space:]]+$//')"
  [ -z "$title" ] && title="$(basename "$f" .md)"
  size=$(stat -f%z "$f" 2>/dev/null || stat -c%s "$f" 2>/dev/null || echo 0)
  NODES=$(echo "$NODES" | jq \
    --arg p "$SOURCE_DIR/$(basename "$f")" \
    --arg a "$f" \
    --arg t "$title" \
    --argjson s "$size" \
    '. + [{"rel_path":$p,"abs_path":$a,"title":$t,"size":$s}]')
done

echo "$(jq -n --argjson files "$NODES" --argjson errors "$ERRORS" \
  '{"files":$files,"errors":$errors}')"
[ "$(echo "$ERRORS" | jq 'length')" -ne 0 ] && exit 1
