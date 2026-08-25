# Init — 初始化知识库（vault 版）

## 前置条件

- vault 根目录 `$VAULT` 可访问（mac/VM 双平台回退）
- 询问用户知识库名称（默认 `my-wiki`），用户可自定义
- **确认 wiki 根目录落点**：必须嵌套在 vault 现有目录内（禁止新建一级目录），默认 `24_阅读思考/<wiki-name>/`，用户可指定其他现有目录（如 `21_ai/`）

## 步骤

### 1. 确定根目录

询问用户：
- 知识库名称 `<WIKI_NAME>`
- 父目录 `<PARENT_DIR>`（vault 现有目录，默认 `24_阅读思考`）

计算根目录相对路径：`ROOT = <PARENT_DIR>/<WIKI_NAME>`（如 `24_阅读思考/my-wiki`）。
记录 `PARENT_DIR`、`ROOT`、`STORAGE_TYPE=vault`。

### 2. 确定 raw 装配模式（**必须等待用户确认后才能继续**）

> **⚠️ 阻断步骤**：必须向用户展示配置摘要并等待明确确认，**禁止跳过或自动使用默认值**。

先确定 raw 层装配模式（默认 `create`）：

- **create（默认）**：本 wiki 新建 `raw/` 及一组子目录，由用户后续往里放素材。
- **reference**：把一棵已有的 vault 目录树（如现有笔记目录）整体引用为 raw 层；原树原地不动、继续由其维护者增删，下游 ingest 实时枚举感知新增。
- **none**：不创建 raw 层。

**若选 create** —— 展示并确认 raw/ 子目录列表：

```
📋 初始化配置确认：
  - 知识库名称：<WIKI_NAME>
  - 根目录：<PARENT_DIR>/<WIKI_NAME>
  - raw 模式：create
  - raw/ 子目录：papers, articles, repos, datasets, images, assets

以上 raw/ 子目录为默认配置，你可以：
  - 直接确认 → 使用默认列表
  - 修改 → 增加、删除、重命名子目录（如删除 datasets，添加 notes）
  - 留空 → 不创建任何 raw/ 子目录

请确认或修改后继续。
```

记录 `RAW_MODE=create` 和最终 RAW_SUBDIRS 列表。

**若选 reference** —— 让用户提供被引用的原目录，并校验：
- 用户给出原目录的 vault 相对路径（如 `24_阅读思考/某主题笔记/`）
- 用 `scripts/list_raw_tree.sh` 列原目录一级子项做预览，请用户确认"就是这棵树"
- 记录 `RAW_MODE=reference`、`RAW_SOURCE_PATH=<原目录相对路径>`，展示摘要等待确认：

```
📋 初始化配置确认：
  - 知识库名称：<WIKI_NAME>
  - 根目录：<PARENT_DIR>/<WIKI_NAME>
  - raw 模式：reference
  - 引用原目录：<原目录路径>
  - 一级子项预览：<列表>

确认后继续。
```

**收到用户确认后**，进入步骤 3。

### 3. 调用初始化脚本

> 脚本已内置所有创建逻辑（文件夹、文档、INDEX 更新、LOG 追加、本地配置保存），串行执行避免竞争。

参照 `adapter/vault.md`「初始化脚本」，通过 Bash 工具调用：

```bash
WIKI_NAME="<WIKI_NAME>" PARENT_DIR="<PARENT_DIR>" \
  RAW_SUBDIRS="<子目录列表空格分隔>" \
  bash <skill_base_dir>/scripts/init.sh
```

> **reference 模式**额外传 `RAW_MODE=reference`、`RAW_SOURCE_PATH=<原目录相对路径>`；此时脚本不创建 raw/ 与子目录，INDEX 的 `raw` 行直接指向原目录。

脚本将依次完成（详见 `scripts/common.sh`）：
1. 创建根目录
2. 创建 raw/ 和 wiki/（reference 模式：跳过 raw/，`raw` 直接用原目录路径）
3. 创建 raw/ 子目录（仅 create 模式遍历 RAW_SUBDIRS；reference/none 跳过）
4. 创建 wiki/ 子目录（sources/entities/concepts/comparisons/overviews）
5. 创建 AGENTS.md、INDEX.md、LOG.md
6. 用所有路径写入 INDEX.md
7. 追加初始化日志到 LOG.md
8. 保存本地配置到 `~/.llm_wiki.setting.json`（vault 路径版）
9. 输出 JSON 摘要

### 4. 向用户报告

读取脚本输出末尾的 JSON 摘要，向用户报告：
- 根目录路径（vault 相对路径）
- INDEX.md 路径
- 目录结构总结（含 raw/ 子目录列表；reference 模式报告"raw 层 = 引用现有目录『<路径>』，子目录由 ingest 实时枚举感知新增"）
- 配置已保存提示

## 注意事项

- 目录创建顺序：根目录 → 一级子目录 → 二级子目录 → 文档
- create 模式共创建 `3 + len(RAW_SUBDIRS) + 5` 个文件夹 + 3 个文档（默认 RAW_SUBDIRS=6 时为 14 个文件夹）
- **reference 模式**只创建 `根目录 + wiki/ + 5 个 wiki 子目录`（不建 raw/），`raw` 指向被引用的原目录
- INDEX.md 的页面路径是后续所有操作的入口
- wiki 根目录嵌套在 vault 现有目录内，不新建 vault 一级目录
