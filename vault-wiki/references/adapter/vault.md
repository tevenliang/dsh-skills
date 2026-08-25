# Vault Adapter — 本地文件存储命令参考

vault 版只有一种存储后端：本地 Obsidian vault 的 Markdown 文件。本文件定义所有底层文件操作的约定，替代飞书版的 `drive.md` / `wiki.md` 两个 adapter。

所有路径均为 **vault 内相对路径**（相对于 `$VAULT`）。读取 `$VAULT` 环境变量；未设按 `platform.system()` 回退：
- macOS: `~/Documents/steven_vault`
- Linux/VM: `/home/ubuntu/webdav/steven_vault`

## 路径解析辅助

所有命令的 `PARENT` / `TARGET` 均为 vault 相对路径。组合为绝对路径：

```bash
VAULT_BASE="${VAULT:-$(
  if [ "$(uname -s)" = "Linux" ]; then echo "/home/ubuntu/webdav/steven_vault";
  else echo "$HOME/Documents/steven_vault"; fi)}"
abs() { echo "$VAULT_BASE/$1"; }
```

## 创建文件夹

```bash
mkdir -p "$(abs "<PARENT>/<NAME>")"
```

- 等价于飞书 `lark-cli drive files create_folder` / `wiki nodes create`
- 返回值为该目录的 vault 相对路径（如 `24_阅读思考/my-wiki/raw/papers`）

## 创建文档

```bash
# 直接用 Write 工具或 heredoc 写入 .md 文件
cat > "$(abs "<PARENT>/<TITLE>.md")" <<'EOF'
<markdown 内容>
EOF
```

- 标题取文件名（或正文首个 `# 一级标题`）
- 长文档分块写入：先写标题骨架，再用 `cat >>` 追加正文

## 列出子项

```bash
# 列出某目录下所有 .md（不含子目录递归）
ls -1 "$(abs "<PARENT>")"/*.md 2>/dev/null
# 或递归枚举
find "$(abs "<PARENT>")" -name '*.md'
```

- 等价于飞书 `lark-cli drive files list` / `wiki nodes list`

## 移动文档

```bash
mv "$(abs "<SRC>")" "$(abs "<DST>")"
```

- 等价于飞书 `drive +move` / `wiki nodes move`

## 复制/上传文件（图片、PDF 等附件）

```bash
cp "<本地文件绝对路径>" "$(abs "<TARGET_DIR>/<FILENAME>")"
```

- 等价于飞书 `drive +upload`
- 引用方式：`![[<相对路径>]]`（Obsidian embed）或 `[[<相对路径>]]`

## 读取文档

```bash
cat "$(abs "<DOC_PATH>")"
# 或用 Read 工具
```

- 等价于飞书 `lark-cli docs +fetch --doc-format markdown`

## 更新文档（追加 / 覆盖 / 局部替换）

```bash
# 追加正文
cat >> "$(abs "<DOC_PATH>")" <<'EOF'
<新增内容>
EOF

# 整篇覆盖（先 Read 再 Write 全量内容）
# 局部替换（精确替换某段落）：用编辑器/脚本 sed 或 LLM 改写后 Write
```

- `append` → `cat >>`
- `overwrite` → Write 全量内容（markdown 必须保留原 `# 一级标题`）
- `str_replace` → 读取后精确替换相关段落再写回

## 递归枚举 raw 子树（reference 模式）

下游 ingest/import 用本脚本实时枚举被引用目录的整棵子树：

```bash
RAW_PATH="<原目录 vault 相对路径>" [MAX_DEPTH=8] \
  bash <skill_base_dir>/scripts/list_raw_tree.sh
```

输出 `{nodes:[{path,title,is_container,depth,rel_path}],errors:[]}`；`is_container=true` 为目录并递归，叶子为 `.md` 文件。

## 初始化脚本

create 模式（默认）：

```bash
WIKI_NAME="<WIKI_NAME>" PARENT_DIR="<现有 vault 目录，如 24_阅读思考>" \
  RAW_SUBDIRS="papers articles repos" bash <skill_base_dir>/scripts/init.sh
```

reference 模式（引用现有目录树为 raw 层）：

```bash
WIKI_NAME="<WIKI_NAME>" PARENT_DIR="<现有 vault 目录>" \
  RAW_MODE="reference" RAW_SOURCE_PATH="<原目录 vault 相对路径>" \
  bash <skill_base_dir>/scripts/init.sh
```

## 说明

- vault 没有「token」概念，所有引用用 vault 相对路径 + `[[wikilink]]`
- vault 没有「快捷方式」概念；reference 模式直接指向原目录真实路径，原目录原地不动
- 文件名即文档标识，重名会覆盖——操作前确认
