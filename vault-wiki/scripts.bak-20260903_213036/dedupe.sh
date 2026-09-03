#!/bin/bash
# dedupe.sh — 识别并删除重复文件（兼容 zsh）
#
# 用法：
#   SOURCE_DIR="21_ai/openclaw" bash dedupe.sh
#
# 输出：JSON { "deleted": [{"path","reason"}], "kept": [{"path","size"}], "errors": [...] }

set -uo pipefail

SOURCE_DIR="${SOURCE_DIR:?需要 SOURCE_DIR}"
CONFIG="${HOME}/.llm_wiki.setting.json"
DRIVE_FOLDER_ID=$(jq -r '.drive_folder_id // empty' "$CONFIG" 2>/dev/null)
DRIVE_FOLDER_NAME=$(jq -r '.drive_folder_name // empty' "$CONFIG" 2>/dev/null)

_vault_base() {
  if [ -n "${VAULT:-}" ]; then echo "$VAULT";
  elif [ "$(uname -s)" = "Linux" ]; then echo "/home/ubuntu/webdav/steven_vault";
  else echo "$HOME/Documents/steven_vault"; fi
}
VB="$(_vault_base)"
ABS="$VB/$SOURCE_DIR"

DELETED="[]"
KEPT="[]"
ERRORS="[]"

# ---------- 辅助函数 ----------
_normalize_name() {
  # 去掉 _2 后缀、emoji 前缀、空格
  printf '%s' "$1" | sed -E \
    - 's/_[0-9]+(\.md)?$//' \
    - 's/^[🏀🎯🚀💡🔥⭐📚💰🎓🛠️🤖📖🎧🎬🔍✨💼🌟📊🎯🌐🎁📝🤔📈💡🌈🎪🌍💻📱🎨📹🔑]+//' \
    - 's/[[:space:]]+//g' \
    | tr '[:upper:]' '[:lower:]'
}

_is_duplicate_keyword() {
  printf '%s' "$1" | grep -qiE '(副本|copy|duplicate|backup)' && return 0
  return 1
}

_get_size() {
  stat -f%z "$1" 2>/dev/null || stat -c%s "$1" 2>/dev/null || echo 0
}

# ---------- 枚举所有叶子 ----------
ALL_FILES=$(find "$ABS" -maxdepth 1 -name "*.md" -type f 2>/dev/null | sort)
if [ -z "$ALL_FILES" ]; then
  echo "$(jq -n --argjson deleted "$DELETED" --argjson kept "$KEPT" --argjson errors "$ERRORS" \
    '{"deleted":$deleted,"kept":$kept,"errors":$errors}')"
  exit 0
fi

# ---------- 构建 normalized_key → files 的映射 ----------
# 用文件拼接来模拟 associative array（bash 3 兼容）
KEY_FILES=""
for f in $ALL_FILES; do
  key="$(_normalize_name "$(basename "$f" .md)")"
  KEY_FILES="${KEY_FILES}${key}|||${f}\n"
done

# 去重 key（保留顺序）
UNIQ_KEYS=$(printf '%s' "$KEY_FILES" | cut -d'|' -f1 | sort -u)

# ---------- 处理每个 key ----------
for key in $UNIQ_KEYS; do
  # 收集该 key 下的所有文件
  group_files=""
  for line in $(printf '%s' "$KEY_FILES" | grep "^${key}|||"); do
    f=$(printf '%s' "$line" | cut -d'|' -f3)
    [ -n "$f" ] && group_files="${group_files}${f}\n"
  done
  
  # 去掉末尾换行
  group_files=$(printf '%s' "$group_files" | sed '$ d')
  
  # 计数
  count=$(printf '%s' "$group_files" | grep -c . 2>/dev/null || echo 0)
  
  # 如果只有一个文件，检查副本关键字
  if [ "$count" -eq 1 ]; then
    f=$(printf '%s' "$group_files")
    if _is_duplicate_keyword "$f"; then
      if rm -f "$f"; then
        DELETED=$(echo "$DELETED" | jq \
          --arg p "${f#$VB/}" --arg r "含副本关键字" \
          '. + [{path:$p,reason:$r}]')
        echo "  删除: $(basename "$f") — 含副本关键字"
      fi
    else
      sz=$(_get_size "$f")
      KEPT=$(echo "$KEPT" | jq \
        --arg p "${f#$VB/}" --argjson s "$sz" \
        '. + [{path:$p,size:$s}]')
    fi
    continue
  fi
  
  # 多个文件 → 找最大
  largest=""
  largest_size=0
  for f in $group_files; do
    [ -z "$f" ] && continue
    sz=$(_get_size "$f")
    if [ "$sz" -gt "$largest_size" ]; then
      largest_size=$sz
      largest="$f"
    fi
  done
  
  # 保留最大，删除其余
  for f in $group_files; do
    [ -z "$f" ] && continue
    if [ "$f" = "$largest" ]; then
      KEPT=$(echo "$KEPT" | jq \
        --arg p "${f#$VB/}" --argjson s "$largest_size" \
        '. + [{path:$p,size:$s}]')
    else
      base=$(basename "$f" .md)
      if [[ "$base" =~ _[0-9]+$ ]]; then
        reason="重复（_N 后缀）"
      elif _is_duplicate_keyword "$f"; then
        reason="含副本关键字"
      else
        reason="重复（同名不同内容）"
      fi
      if rm -f "$f"; then
        DELETED=$(echo "$DELETED" | jq \
          --arg p "${f#$VB/}" --arg r "$reason" \
          '. + [{path:$p,reason:$r}]')
        echo "  删除: $(basename "$f") — $reason"
      fi
    fi
  done
done

echo ""
echo "$(jq -n \
  --argjson deleted "$DELETED" \
  --argjson kept "$KEPT" \
  --argjson errors "$ERRORS" \
  '{"deleted":$deleted,"kept":$kept,"errors":$errors}')"
