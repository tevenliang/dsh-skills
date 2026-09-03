#!/bin/bash
# init.sh — vault 版知识库初始化脚本（本地文件操作）
#
# 用法：
#   WIKI_NAME="my-wiki" PARENT_DIR="24_阅读思考" \
#     RAW_SUBDIRS="papers articles repos" bash init.sh
#
#   WIKI_NAME="my-wiki" PARENT_DIR="24_阅读思考" \
#     RAW_MODE="reference" RAW_SOURCE_PATH="24_阅读思考/某主题笔记" bash init.sh
#
# 必填环境变量：
#   WIKI_NAME     知识库名称
#   PARENT_DIR    wiki 根目录所在的现有 vault 目录（如 24_阅读思考），禁止新建一级目录
#   RAW_SUBDIRS   空格分隔的 raw/ 子目录列表（仅 RAW_MODE=create 使用）
#
# 可选环境变量（raw 层装配模式）：
#   RAW_MODE              create（默认）| reference | none
#   RAW_SOURCE_PATH       reference 模式必填：原目录 vault 相对路径
#
# 依赖: jq, python3（save_config.py）

set -e

: "${WIKI_NAME:?需要设置 WIKI_NAME}" \
  "${PARENT_DIR:?需要设置 PARENT_DIR（现有 vault 目录，如 24_阅读思考）}"
RAW_SUBDIRS="${RAW_SUBDIRS:-}"
RAW_MODE="${RAW_MODE:-create}"
RAW_SOURCE_PATH="${RAW_SOURCE_PATH:-}"

case "$RAW_MODE" in
  create|reference|none) ;;
  *) echo "ERROR: RAW_MODE 必须是 create | reference | none，当前值: $RAW_MODE" >&2; exit 1 ;;
esac

if [[ "$RAW_MODE" == "reference" ]]; then
  : "${RAW_SOURCE_PATH:?reference 模式需要 RAW_SOURCE_PATH（原目录 vault 相对路径）}"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

# ---------- vault 适配 ----------

_create_dir() {
  local name="$1" parent="$2"
  local rel_path="${parent}/${name}"
  mkdir -p "$(_vault_base)/${rel_path}"
  echo "$rel_path"
}

_create_doc() {
  # title parent_path markdown
  _create_doc_v2 "$1" "$2" "$3"
}

# ---------- 执行初始化 ----------

run_init
