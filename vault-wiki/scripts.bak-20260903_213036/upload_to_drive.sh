#!/bin/bash
# upload_to_drive.sh — 将源目录叶子 md 上传到 Google Drive
#
# 用法：
#   SOURCE_DIR="21_ai/openclaw" DRIVE_FOLDER_ID="xxx" bash upload_to_drive.sh
#
# 输出：JSON { "uploaded": [{"local","drive_id","drive_name"}], "errors": [...] }
# 依赖：gog CLI（已认证 Drive）

set -uo pipefail

SOURCE_DIR="${SOURCE_DIR:?需要 SOURCE_DIR}"
DRIVE_FOLDER_ID="${DRIVE_FOLDER_ID:?需要 DRIVE_FOLDER_ID}"

CONFIG="${HOME}/.llm_wiki.setting.json"
GOG_ACCOUNT="${GOG_ACCOUNT:-teven.liang@gmail.com}"

_vault_base() {
  if [ -n "${VAULT:-}" ]; then echo "$VAULT";
  elif [ "$(uname -s)" = "Linux" ]; then echo "/home/ubuntu/webdav/steven_vault";
  else echo "$HOME/Documents/steven_vault"; fi
}
VB="$(_vault_base)"
ABS="$VB/$SOURCE_DIR"

UPLOADED="[]"
ERRORS="[]"

# 安全文件名：去掉 / 空格，加前缀
_safe_name() {
  local f="$1"
  local base="$(basename "$f" .md)"
  # 一级_二级_文件名
  local prefix="${SOURCE_DIR//\//_}"
  echo "${prefix}_${base}.md" | sed 's/[[:space:]]/_/g; s|/|_|g'
}

echo "📤 开始上传 $SOURCE_DIR 的叶子文件到 Drive..."

for f in "$ABS"/*.md; do
  [ -f "$f" ] || continue
  fname="$(basename "$f")"
  safe_name="$(_safe_name "$f")"
  
  echo "  上传: $fname → $safe_name"
  
  # 用 gog upload，输出 JSON
  result=$(gog drive upload "$f" \
    --parent "$DRIVE_FOLDER_ID" \
    --name "$safe_name" \
    --account "$GOG_ACCOUNT" \
    --json --no-input 2>&1)
  
  if [ $? -eq 0 ]; then
    drive_id=$(echo "$result" | jq -r '.file.id // .id // empty' 2>/dev/null)
    drive_name=$(echo "$result" | jq -r '.file.name // .name // empty' 2>/dev/null)
    if [ -n "$drive_id" ]; then
      UPLOADED=$(echo "$UPLOADED" | jq \
        --arg l "${f#$VB/}" \
        --arg i "$drive_id" \
        --arg n "$safe_name" \
        '. + [{local:$l,drive_id:$i,drive_name:$n}]')
      echo "    ✅ Drive ID: $drive_id"
    else
      ERRORS=$(echo "$ERRORS" | jq \
        --arg f "$fname" --arg m "gog 上传成功但无法解析 drive_id: $result" \
        '. + [{context:"upload","kind":"parse_error","message":$m,"file":$f}]')
      echo "    ⚠️ 无法解析 Drive ID: $result"
    fi
  else
    ERRORS=$(echo "$ERRORS" | jq \
      --arg f "$fname" --arg m "$result" \
      '. + [{context:"upload","kind":"upload_error","message":$m,"file":$f}]')
    echo "    ❌ 上传失败: $result"
  fi
done

echo ""
echo "$(jq -n \
  --argjson uploaded "$UPLOADED" \
  --argjson errors "$ERRORS" \
  '{"uploaded":$uploaded,"errors":$errors}')"

[ "$(echo "$ERRORS" | jq 'length')" -ne 0 ] && exit 1
