#!/bin/bash
# backlink.sh — 向每个叶子 md 追加/更新关联 wiki 段
#
# 用法：
#   WIKI_PAGE="21_ai/openclaw-wiki" SOURCE_DIR="21_ai/openclaw" bash backlink.sh
#
# 每个叶子末尾追加：
#   ---
#   ## 关联 wiki
#   本文收录于 [[21_ai/openclaw-wiki]]
#
# 若已存在 ## 关联 wiki 段，则替换其内容（不重复追加）。

set -uo pipefail

WIKI_PAGE="${WIKI_PAGE:?需要 WIKI_PAGE（不含 .md）}"
SOURCE_DIR="${SOURCE_DIR:?需要 SOURCE_DIR}"

_vault_base() {
  if [ -n "${VAULT:-}" ]; then echo "$VAULT";
  elif [ "$(uname -s)" = "Linux" ]; then echo "/home/ubuntu/webdav/steven_vault";
  else echo "$HOME/Documents/steven_vault"; fi
}
VB="$(_vault_base)"
ABS="$VB/$SOURCE_DIR"

BACKLINK_BLOCK="
---

## 关联 wiki

本文收录于 [[${WIKI_PAGE}]]
"

count=0
for f in "$ABS"/*.md; do
  [ -f "$f" ] || continue
  
  # 检查是否已有 ## 关联 wiki 段
  if grep -q "^## 关联 wiki" "$f"; then
    # 替换已有段（从 ## 关联 wiki 到文件末尾）
    tmp=$(mktemp)
    sed '/^## 关联 wiki$/,/^$/d' "$f" > "$tmp"
    printf '\n%s\n' "$BACKLINK_BLOCK" >> "$tmp"
    mv "$tmp" "$f"
    echo "  🔄 更新: $(basename "$f")"
  else
    printf '\n%s\n' "$BACKLINK_BLOCK" >> "$f"
    echo "  ➕ 追加: $(basename "$f")"
  fi
  ((count++))
done

echo "✅ 完成，共处理 $count 个叶子 md"
