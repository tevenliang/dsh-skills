# Import — 导入原始素材（vault 版）

核心理念：raw/ 是知识库的输入层，素材质量决定知识层深度。LLM 协助用户将分散的素材（vault 内 md、本地文件、外部链接）统一归档到 raw/ 对应子目录，保持原始内容不加工，为后续 ingest 做准备。

## 前置条件

- Wiki 已初始化
- 从 `~/.llm_wiki.setting.json` 读取 wiki 根路径、`storage_type=vault`、raw 配置
- **Wiki 确认**：如果本地配置中 wikis ≥ 2，在选择目标 wiki 后，**必须**向用户确认选中的 wiki 名称再继续，此操作不可逆，避免写入错误的知识库
- 已 Read AGENTS.md 查看规范
- 用户提供以下之一：vault 内/本地 md 路径、本地文件路径、外部 URL

## 素材类型识别

| 用户输入形式 | 识别类型 | 处理分支 |
|------------|---------|---------|
| vault 内或本地 `.md` / `.txt` 路径（`/` 或 `~/` 开头，或 vault 相对路径） | Markdown 文档 | → 分支 A |
| 本地非 md 文件（PDF/图片/代码等路径） | 本地附件 | → 分支 B |
| arXiv / GitHub / HTTP(S) URL | 外部链接 | → 分支 C |

## 目录分类规则

> **适用范围**：本节的「按子目录名自动归类」仅用于 `raw_mode=create`。`raw_mode=reference` 见下方「reference 模式」说明。

create 模式下，raw/ 子目录由 init 时用户自定义，从 INDEX.md 目录配置表动态读取。根据子目录名称做智能匹配：

| 子目录名称 | 自动匹配条件（按优先级） |
|-----------|----------------------|
| `papers` | arXiv 链接；`.pdf` 文件；标题含"论文"、"paper"、"survey" |
| `repos` / `code` | GitHub repo URL；代码文件（.py、.ts、.go 等） |
| `articles` | Medium、Substack、博客、新闻 URL；`.md`、`.txt`（默认） |
| `datasets` / `data` | `.csv`、`.json`、`.parquet`、`.jsonl` |
| `images` / `media` | `.jpg`、`.jpeg`、`.png`、`.svg`、`.gif`、`.webp` |
| `assets` | 以上均不匹配的兜底目录 |

> - 对于用户自定义的非标准名称（如 `notes`、`references`），LLM 根据名称语义和素材内容智能判断。
> - 如有歧义或无法确定目标子目录，向用户确认后再继续。
> - 若只有一个 raw/ 子目录，直接使用无需匹配。

### reference 模式

`raw_mode=reference` 时，raw 是一棵外部维护的现有目录树，没有静态 `raw/<子目录>` 行，**不适用上面的自动归类**：

- raw 层主要由原树维护者直接增删，import 不是主路径；新素材一般由用户在原树里直接添加，再由 ingest 实时枚举感知。
- 若确需通过本流程把一篇 md/文件放进原树某子目录：用 `scripts/list_raw_tree.sh` 实时列出原树的容器型子目录，向用户展示供选择，把选中目录的相对路径作为 TARGET_PATH。

## 步骤

### 步骤 1：读取 INDEX.md，确定目录配置

- 读取 `~/.llm_wiki.setting.json` 获取 wiki 根路径、`storage_type`、`raw_mode`（及 reference 模式的 `raw_source_path`）
- `Read` `wiki/INDEX.md`
- 解析「Wiki 配置」获取 `raw_mode`（及 reference 模式的 raw_source_path）
- **create 模式**：解析「目录配置」表，提取所有 raw/ 子目录的相对路径 → 构建映射 `{子目录名 → 相对路径}`
- **reference 模式**：无静态子目录行，按「reference 模式」用 `list_raw_tree.sh` 实时列出可选目标目录

### 步骤 2：识别素材类型和目标目录

- 根据「素材类型识别」表确定处理分支（A / B / C）
- **create 模式**：根据「目录分类规则」和 INDEX.md 中的 raw/ 子目录列表确定目标子目录，记录 TARGET_PATH（相对路径）和 TARGET_SUBDIR（如 `raw/papers/`）
- **reference 模式**：从实时枚举的原树容器型子目录中由用户选定 TARGET_PATH
- 如有歧义，向用户确认

### 步骤 3：执行导入操作（按分支执行）

**分支 A — Markdown 文档**

- 展开路径（`~` → 绝对路径），确认文件可读
- 从路径提取 FILENAME，默认 TITLE = 去掉扩展名的文件名（用户可覆盖）
- **⚠️ 阻断操作：执行前必须向用户确认导入方式（默认复制）**：

  > 检测到文档「**<TITLE>**」，请确认导入方式：
  >
  > - **[默认] 复制**：将文件复制到 `<TARGET_SUBDIR>`，原文件保留原位
  > - **移动**：将文件移动到 `<TARGET_SUBDIR>`，原位置不再保留
  >
  > 请回复 **1（复制）** 或 **2（移动）**，直接回车默认选 1：

- 根据用户选择执行 `cp` 或 `mv` 到 TARGET_PATH
- 记录 RAW_REFERENCE = `[[<TARGET_SUBDIR>/<FILENAME>.md]]`

**分支 B — 本地附件（PDF / 图片 / 代码等）**

- 展开路径，确认文件可读
- 从路径提取 FILENAME，默认 TITLE = 去掉扩展名的文件名（用户可覆盖）
- `cp "<本地文件绝对路径>" "$(abs <TARGET_PATH>/<FILENAME>)"`
- 记录 RAW_REFERENCE = `![[<TARGET_SUBDIR>/<FILENAME>]]`（Obsidian embed）或 `[[<TARGET_SUBDIR>/<FILENAME>]]`

**分支 C — 外部链接**

- 记录原始 URL，记录 SOURCE_URL
- **使用 webclip-cli 工具抓取页面全文和媒体文件**：
  ```
  webclip-cli "<SOURCE_URL>"
  ```
  - **必须使用本地全局安装的 `webclip-cli` 命令，禁止用 `npx github:...` 形式调用**
  - 调用前先 `command -v webclip-cli` 校验；若不存在，提示用户运行 `npm install -g github:harryzhz/webclip-cli` 完成全局安装后再继续，**禁止回退到 `npx`**
  - 工具自动处理 JS 渲染页面；输出 JSON 到 stdout，日志到 stderr
  - 解析 JSON 提取：`title`、`markdown`、`media`（`{type,index,alt,originalUrl,localPath,success}`）、`stats`、`outputDir`
  - 若工具退出码非 0 或 `stats.charCount < 200`，提示用户手动复制内容后另存为本地 .md 文件，再改走分支 A/B
- **向用户展示内容预览**（标题 + 字符数/段落数 + 媒体数量 + 前 3 段），确认抓取内容符合预期后再创建文档
- 在 raw/ 对应子目录创建 Markdown 文件：
  - 来源注释置于文档最顶部：
    ```markdown
    > **原始来源**: <SOURCE_URL>
    > **抓取时间**: <ISO_DATE>
    ```
  - 完整正文写入文件（不得因过长截断——必须全部写入）
- 记录 RAW_REFERENCE = `[[<TARGET_SUBDIR>/<FILENAME>.md]]`

### 步骤 4：向用户展示操作结果

```
素材类型：[Markdown 文档 / 本地附件 / 外部链接]
标题：<TITLE>
目标目录：<TARGET_SUBDIR>
vault 路径：<相对路径>
```

### 步骤 5：追加 LOG

向 `wiki/LOG.md` 追加 IMPORT 日志条目（格式见 [pages.md](../templates/pages.md)）。

### 步骤 6：报告结果，询问是否 ingest

- 输出素材标题、存入目录、vault 路径
- 询问用户：

  > 素材已存入 `<TARGET_SUBDIR>`。是否立即执行 **ingest**，将其摄入到 wiki 知识层？

## 注意事项

- raw/ 内容存入后**不做任何修改**（分支 C 的来源注释除外，属于元数据补充）
- 分支 A 移动文件会改变文件位置，但不影响内容
- 分支 C 的 raw 文件标题即为抓取的页面标题，**不加 "Source:" 前缀**（raw/ 层不使用 wiki/ 层的命名约定）
- 批量导入多个素材时：逐条执行步骤 2-5，最后统一追加一条汇总 LOG（列出每个引用及目标目录）
