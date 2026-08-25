# Ingest — 摄入源文档（vault 版）

## 前置条件

- Wiki 已初始化
- 从 `~/.llm_wiki.setting.json` 读取 wiki 根路径、`storage_type=vault`
- **Wiki 确认**：如果本地配置中 wikis ≥ 2，在选择目标 wiki 后，**必须**向用户确认选中的 wiki 名称再继续，此操作不可逆，避免写入错误的知识库
- 用户已将原始素材放入 raw/ 对应子目录（LLM 不写入 raw/）；**reference 模式**下素材在被引用的原目录里，由原树维护者增删，LLM 通过步骤 1.5 实时枚举感知
- 已 Read AGENTS.md 查看规范

## 步骤

1. **读取 INDEX.md**
   - 读取 `~/.llm_wiki.setting.json` 获取 wiki 根路径
   - `Read` `wiki/INDEX.md`
   - 解析：目录配置 → 获取所有子目录的 vault 相对路径；Wiki 配置 → 获取 `raw_mode` / `raw_source_path`；页面注册表 → 构建 path_map: {标题 → 相对路径}
   - **reference 模式**：「目录配置」表只有一行 `| raw | <原目录路径> |`、没有 `raw/<子目录>` 行，这是正常的，不要因找不到子目录而报错

   **步骤 1.5 — 枚举 raw 待摄入素材**（`raw_mode=reference` 时必做；`create` 模式下用户通常直接指定素材，可跳过）
   - reference 模式下 raw 引用的是一棵外部维护、会持续新增的现有目录树，必须实时枚举才能发现新增的子目录/文档：
     ```bash
     RAW_PATH="<原目录相对路径>" bash <skill_base_dir>/scripts/list_raw_tree.sh
     ```
   - 输出 `{nodes:[{path,title,is_container,depth,rel_path}],errors:[]}`
   - **若 errors 非空或脚本非 0 退出：立即中止枚举，不得把本次结果当作「无新增」**（否则会漏摄）
   - 取 `nodes` 中可摄入项（`.md` 文件，即叶子），与「页面注册表」**Raw 列**已登记的路径求差集 → 得到「未摄入素材」清单
   - 对已登记的 raw 路径，交给步骤 2 的 `check_staleness.sh` 判定是否需 re-ingest
   - 向用户按 `path` 列出「发现 N 个未摄入素材 + M 个已更新」，确认后对每个素材依次执行步骤 3 及之后

2. **检查已有 Source 页面是否过时**
   - 从 INDEX.md 页面注册表中筛选所有 `类型=source` 的条目
   - **范围确定**：
     - 如果用户指定了 ingest 的目标 raw 文档 → 仅检查引用这些 raw 文档的 Source 页面
     - 如果用户未指定范围（如"检查有没有需要更新的"）→ 扫描全部 Source 页面
   - 对范围内的 Source 页面，逐个 Read 并提取：
     - `原始来源` 中 `[[...]]` 的 raw 相对路径
     - `updated` 中的时间戳
     - raw 文件的类型（md / 附件）
   - 构造 JSON 数组，调用过时检测脚本：
     ```bash
     echo '<JSON_ARRAY>' | bash <skill_base_dir>/scripts/check_staleness.sh
     ```
     输入格式: `[{"source_title":"...","raw_path":"...","raw_doc_type":"md","recorded_update":"YYYY-MM-DD HH:mm"}]`
   - 解析脚本输出（基于文件 mtime 对比），向用户报告：
     - **过时的 Source 页面**（raw 文件有更新）：建议重新摄入
     - **缺失的 raw 文件**：raw 路径指向的文件不存在
     - **检查错误**：如果输出含 `errors` 或脚本非 0 退出，必须中止 stale 判断
     - **新鲜的 Source 页面**：无需处理
   - 用户确认后：
     - 对过时的 Source 页面：重新读取 raw 内容，走后续 ingest 流程更新 Source 及关联页面
     - 跳过无需更新的页面

3. **读取源内容**
   - Markdown：`Read` `<RAW_PATH>`，记录 RAW_PATH
   - 附件（PDF、图片等）：用 Read 工具读取（PDF 可提取文字），记录 RAW_PATH
   - Source 页「原始来源」统一使用 raw 引用：`[[<RAW_PATH>]]` 或 `![[<RAW_PATH>]]`

4. **分析源内容**
   - 提取实体、概念、关键要点
   - 对照 path_map 识别与已有页面的关联

   #### 实体 (Entity) 识别标准
   - 命名实体：具体的人物、组织、产品、工具、系统、地点
   - 必须在源文档中被实质性讨论（非一笔带过的提及）
   - 判断门槛：能从该源文档中提取 **≥3 条关键事实** → 建页；否则仅在 Source 摘要中内联提及
   - 检查 path_map 避免同义词/中英文重复建页

   #### 概念 (Concept) 识别标准
   - 抽象思想：理论、方法论、模式、原则、技术、框架
   - 源文档中有定义或解释（非仅提及名称）
   - 可跨源复用：阅读其他源文档时这个概念页能提供上下文价值
   - 判断门槛：能写出有意义的「定义」+「详细说明」→ 建页；否则仅在 Source 摘要中内联提及

   #### 粒度控制
   - 宁可少而精，不要多而浅
   - 不确定时，在 Source 摘要的提取列表中标注 `(待确认)`，等后续源文档积累更多信息再建页

5. **提取预览**（默认开启，可在 AGENTS.md「领域约定」中配置为关闭）
   - 向用户展示：
     - 源文档摘要（3 句话）
     - 拟提取的实体列表，每项标注：**新建** / **更新已有** + 简要理由
     - 拟提取的概念列表，每项标注：**新建** / **更新已有** + 简要理由
     - 不建页但会内联提及的项（低于建页门槛的实体/概念）
   - 用户可：添加遗漏项 / 移除不需要的项 / 合并相似项 / 直接确认
   - 确认后进入写入步骤

6. **在 wiki/sources/ 创建或更新 Source 摘要页**
   - 用 Write 工具在 `wiki/sources/` 创建文件，标题为 `Source: <标题>`，内容为 Source 模板（含 YAML frontmatter）
   - 记录 SOURCE_PATH
   - 如果步骤 2 已确认既有 Source 过时，则更新该 Source；否则创建新的 Source 摘要页
   - `updated` 填入当前时间，精确到分钟（格式: YYYY-MM-DD HH:mm）

7. **在 wiki/entities/ 处理实体**
   - 已存在：`Read` 后追加新来源段落，再 `Write` 回写
   - 新建：在 `wiki/entities/` 创建文件（内容过长时同步骤 6 分段写入）
   - 禁止重复写入同名段落（如写两次 "## 相关实体"），每个段落标题在页面中只能出现一次

8. **在 wiki/concepts/ 处理概念**
   - 参照步骤 7 的处理方式，将目录替换为 `wiki/concepts/`，同样注意不要重复段落

9. **补充交叉引用**
   - 回填 Source 页面中的占位引用（用 `[[目标页面路径]]`）
   - 更新相关页面的出链/入链信息，供 INDEX.md 结构化召回使用

10. **更新 INDEX.md 页面注册表**
    - INDEX.md 完全由 LLM 拥有，且步骤 1 已读全；合并新增/变更后**首选整篇重写**：
      - `Read` 当前 INDEX.md → 合并新增/变更行 → `Write` 全量内容（保留 `# INDEX` 一级标题）
    - 仅改个别字段（如「页面总数」「最后更新」）时，精确替换那一行
    - 新增/更新行必须写入：路径、别名、标签、Raw、出链、入链、证据数、摘要；旧 INDEX 缺列时按空值读取，写回时补齐扩展列

11. **追加 LOG**
    - 向 `wiki/LOG.md` 追加 INGEST 条目

12. **报告结果**

## 注意事项

- raw/ 由用户维护，LLM 只读不写
- 所有新文档放入对应子目录，路径从 INDEX.md「目录配置」表获取
- Source 摘要页的「原始来源」字段统一使用 `[[...]]` / `![[...]]` 引用 raw/ 下的素材，禁止使用原始 URL
- **每个段落标题不得重复**，避免出现两个 "## 相关实体" 等
- **内容过长时分段写入** — 先写标题骨架，再 `cat >>` 追加正文
