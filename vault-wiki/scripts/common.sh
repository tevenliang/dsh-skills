#!/bin/bash
# common.sh — init.sh 共用函数库（vault 版）
# 使用方式：source "$(dirname "$0")/common.sh"

WIKI_SUBDIRS="sources entities concepts comparisons overviews"

# raw 层装配模式默认值（init.sh 通常已定义；此处兜底，便于单独 source 调用）
RAW_MODE="${RAW_MODE:-create}"
RAW_SOURCE_PATH="${RAW_SOURCE_PATH:-}"

# ---------- vault 根解析 ----------
_vault_base() {
  if [ -n "${VAULT:-}" ]; then
    echo "$VAULT"
  elif [ "$(uname -s)" = "Linux" ]; then
    echo "/home/ubuntu/webdav/steven_vault"
  else
    echo "$HOME/Documents/steven_vault"
  fi
}

# ---------- 模板函数 ----------

agents_markdown() {
  cat <<'MD'
---
type: agents
---

本文档定义此 LLM Wiki 的结构约定和行为规范。LLM 在执行 ingest/query/lint 操作时必须遵循这些规则。用户和 LLM 共同维护此文档，随着知识库演进持续完善。

## 页面类型

| 类型 | 标题前缀 | 存放目录 | 说明 |
|------|---------|---------|------|
| source | Source: | wiki/sources/ | 对 raw/ 素材的分析摘要 |
| entity | Entity: | wiki/entities/ | 人物、组织、工具、项目等 |
| concept | Concept: | wiki/concepts/ | 方法论、模式、理论等 |
| comparison | Comparison: | wiki/comparisons/ | 对比分析（通常由 query 产出） |
| overview | Overview: | wiki/overviews/ | 主题综述（通常由 query 产出） |

## 命名规范

- 标题前缀严格遵循上表
- Entity 以名词命名，Concept 以主题命名
- Source 标题取原文标题，过长时适当缩写

## 引用规范

- 文档内所有对 raw 素材/其他页面的引用统一使用 `[[wikilink]]`（Obsidian 双向链接）
- 外部链接保留原始 URL（不受此限制）
- INDEX.md 页面注册表的「路径」列同样使用 vault 相对路径

## 工作流规则

- **ingest**: 用户将素材放入 raw/ 后通知 LLM → LLM 从 raw/ 读取内容 → 在 wiki/ 创建 Source 摘要和关联页面 → Source 页的「原始来源」用 `[[...]]` 引用 raw/ 下的素材
- **query**: 从 INDEX.md 定位相关页面 → Read 并综合回答 → 有价值的回答归档为 Overview/Comparison 回流到 wiki
- **lint**: 检查矛盾、过时声明、孤立页、缺失页面、断链、交叉引用缺失 → 生成报告 → 建议新问题和新源

## 领域约定

> 以下为默认配置，可根据使用习惯调整

- **提取粒度**: 精选（仅提取有充分信息支撑的实体/概念，≥3 条关键事实）
- **摄入模式**: 交互式（提取前展示预览并等待确认）
- **归档策略**: 推荐归档（对比分析和综述主动推荐，用户一键确认）
- **领域关键词**: （用户填写，帮助 LLM 识别领域内的重要实体和概念）

（由用户和 LLM 在使用过程中逐步补充，例如：）
（- 本知识库聚焦的领域和范围）
（- 特定术语的翻译或命名约定）
MD
}

log_init_markdown() {
  cat <<'MD'
# 操作日志

最新操作在最下方。
MD
}

# ---------- INDEX 全量内容 ----------
# 依赖环境变量（由 run_init 在调用前设置）：
#   WIKI_NAME, PARENT_DIR, RAW_MODE, RAW_SOURCE_PATH
#   ROOT_PATH, RAW_PATH, RAW_PATH_TABLE, WIKI_PATH
#   PATH_sources/entities/concepts/comparisons/overviews
#   AGENTS_PATH, LOG_PATH, TODAY

build_index_markdown() {
  local root="$PARENT_DIR/$WIKI_NAME"
  cat <<MD
# INDEX

> LLM Wiki 索引 — 所有页面的注册表和导航入口。

## 目录配置

> Path 列为 vault 内相对路径（相对 \$VAULT）。reference 模式下 \`raw\` 行指向被引用的原目录，其子目录不静态登记，由下游实时枚举。

| 目录 | Path |
|------|------|
| root (${WIKI_NAME}) | ${root} |
| raw | ${RAW_PATH} |
${RAW_PATH_TABLE}| wiki | ${WIKI_PATH} |
| wiki/sources | ${PATH_sources} |
| wiki/entities | ${PATH_entities} |
| wiki/concepts | ${PATH_concepts} |
| wiki/comparisons | ${PATH_comparisons} |
| wiki/overviews | ${PATH_overviews} |

## Wiki 配置

| 键 | 值 |
|---|---|
| wiki_name | ${WIKI_NAME} |
| storage_type | vault |
| parent_dir | ${PARENT_DIR} |
| raw_mode | ${RAW_MODE} |
| raw_source_path | ${RAW_SOURCE_PATH:--} |
| 创建时间 | ${TODAY} |
| 最后更新 | ${TODAY} |
| 页面总数 | 0 |

> - \`storage_type\`：固定 \`vault\`（本地 Obsidian vault）
> - \`raw_mode\`：\`create\`（本 wiki 自建 raw/ 子目录）或 \`reference\`（引用现有目录树）或 \`none\`
> - \`raw_source_path\`：仅 reference 模式有值，为原目录 vault 相对路径（无则填 \`-\`）

## 页面注册表

| 标题 | 类型 | 路径 | 目录 | 最后更新 | 关联 | 别名 | 标签 | Raw | 出链 | 入链 | 证据数 | 摘要 |
|------|------|------|------|---------|------|------|------|-----|------|------|--------|------|
MD
}

# ---------- LOG 初始化条目 ----------

build_log_entry() {
  local raw_count
  raw_count=$(echo "$RAW_SUBDIRS" | wc -w | tr -d ' ')
  cat <<MD

---

### ${TODAY} INIT

- 操作: 初始化知识库
- 存储模式: vault
- raw 模式: ${RAW_MODE}
MD
  if [[ "$RAW_MODE" == "reference" ]]; then
    cat <<MD
- raw 引用源: ${RAW_SOURCE_PATH}
- 创建文件夹: 0 raw（引用现有树）+ 5 wiki 子目录
MD
  else
    cat <<MD
- raw/ 子目录: ${RAW_SUBDIRS}
- 创建文件夹: ${raw_count} raw 子目录 + 5 wiki 子目录
MD
  fi
}

# ---------- 文档创建（vault 版）----------
# 直接写 .md 文件；标题取文件名，正文用 heredoc。
# 输出兼容旧契约的 JSON：{data:{doc_id,doc_url}} → vault 版改为 {data:{path,url}}
_create_doc_v2() {
  local title="$1" parent_path="$2" markdown="$3" abs_path doc_path
  doc_path="${parent_path}/${title}.md"
  abs_path="$(_vault_base)/${doc_path}"
  mkdir -p "$(dirname "$abs_path")"
  if [ -n "$(printf '%s' "$markdown" | tr -d '[:space:]')" ]; then
    printf '%s\n' "$markdown" > "$abs_path"
  else
    printf '%s\n' "# ${title}" > "$abs_path"
  fi
  jq -n --arg p "$doc_path" --arg u "obsidian://open?path=${abs_path}" '{data:{path:$p,url:$u}}'
}

# ---------- 主初始化流程 ----------
# 要求调用前已定义：
#   _create_dir "$name" "$parent_path"   → 输出 vault 相对路径字符串
#   _create_doc "$title" "$parent_path" "$markdown" → 输出 JSON（含 .data.path 和 .data.url）
#   WIKI_NAME, PARENT_DIR, RAW_SUBDIRS

run_init() {
  local vb; vb="$(_vault_base)"
  # --- [1/9] 根目录 ---
  echo "=== [1/9] 创建根目录: $WIKI_NAME ==="
  ROOT_PATH=$(_create_dir "$WIKI_NAME" "$PARENT_DIR")
  echo "ROOT_PATH=$ROOT_PATH"

  # --- [2/9] raw/ 和 wiki/ ---
  echo "=== [2/9] 创建 raw/ 和 wiki/ ==="
  case "$RAW_MODE" in
    reference)
      RAW_PATH="$RAW_SOURCE_PATH"
      echo "RAW_PATH=$RAW_PATH (reference: 引用现有目录，不新建 raw/)"
      ;;
    none)
      RAW_PATH="-"
      echo "RAW_PATH=- (none: 不创建 raw 层)"
      ;;
    *)
      RAW_PATH=$(_create_dir "raw" "$ROOT_PATH")
      echo "RAW_PATH=$RAW_PATH"
      ;;
  esac
  WIKI_PATH=$(_create_dir "wiki" "$ROOT_PATH")
  echo "WIKI_PATH=$WIKI_PATH"

  # --- [3/9] raw/ 子目录 ---
  echo "=== [3/9] 创建 raw/ 子目录 ==="
  RAW_PATH_TABLE=""
  if [[ "$RAW_MODE" == "create" ]]; then
    for subdir in $RAW_SUBDIRS; do
      echo "  创建 raw/$subdir ..."
      local_path=$(_create_dir "$subdir" "$RAW_PATH")
      echo "  raw/$subdir => $local_path"
      RAW_PATH_TABLE+="| raw/${subdir} | ${local_path} |"$'\n'
    done
  else
    echo "  ($RAW_MODE 模式：raw 子目录不静态登记，由下游实时枚举)"
  fi

  # --- [4/9] wiki/ 子目录 ---
  echo "=== [4/9] 创建 wiki/ 子目录 ==="
  for subdir in $WIKI_SUBDIRS; do
    echo "  创建 wiki/$subdir ..."
    local_path=$(_create_dir "$subdir" "$WIKI_PATH")
    echo "  wiki/$subdir => $local_path"
    declare "PATH_${subdir}=$local_path"
  done

  # --- [5/9] AGENTS.md ---
  echo "=== [5/9] 创建 AGENTS.md ==="
  local agents_result abs_agents
  agents_result=$(_create_doc "AGENTS" "$ROOT_PATH" "$(agents_markdown)")
  AGENTS_PATH=$(echo "$agents_result" | jq -r '.data.path')
  echo "AGENTS_PATH=$AGENTS_PATH"

  # --- [6/9] INDEX.md ---
  echo "=== [6/9] 创建 INDEX.md ==="
  local index_result abs_index
  index_result=$(_create_doc "INDEX" "$WIKI_PATH" "# INDEX

> LLM Wiki 索引 — 占位，稍后填入完整内容。")
  INDEX_PATH=$(echo "$index_result" | jq -r '.data.path')
  echo "INDEX_PATH=$INDEX_PATH"

  # --- [7/9] LOG.md ---
  echo "=== [7/9] 创建 LOG.md ==="
  TODAY=$(date "+%Y-%m-%d %H:%M")
  local log_result
  log_result=$(_create_doc "LOG" "$WIKI_PATH" "$(log_init_markdown)")
  LOG_PATH=$(echo "$log_result" | jq -r '.data.path')
  echo "LOG_PATH=$LOG_PATH"

  # --- [8/9] 写入 INDEX.md 正文 ---
  echo "=== [8/9] 写入 INDEX.md 正文（填入所有路径）==="
  build_index_markdown > "$(_vault_base)/${INDEX_PATH}"

  # --- [9/9] 追加 LOG 条目 ---
  echo "=== [9/9] 追加 LOG 初始化条目 ==="
  { echo ""; build_log_entry; } >> "$(_vault_base)/${LOG_PATH}"

  # --- 保存配置 + 输出摘要 ---
  echo "=== 初始化完成 ==="
  echo ""
  echo "INIT_RESULT_JSON:"
  export WIKI_NAME PARENT_DIR RAW_SUBDIRS TODAY \
         RAW_MODE RAW_SOURCE_PATH \
         ROOT_PATH RAW_PATH WIKI_PATH \
         INDEX_PATH LOG_PATH AGENTS_PATH
  python3 "$SCRIPT_DIR/save_config.py"
}
