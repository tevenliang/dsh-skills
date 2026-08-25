# 用户偏好（Steven Liang）— common-report 适用

## 三段式报告结构（2026-07-26 用户明确）

用户原话：
> "之前你生成的汇报，这个维度的汇报可以看到整个爬取那个技术环节话的时间多"

**核心维度**：「按操作 op 拆解」（extract_audio / transcribe_groq / transcribe_bailian / summarize_glm 等）

**配套维度**：
1. 总览（平台列表 + 产出 + 总耗时）
2. 各平台阶段耗时（入站/出站）+ 本平台博主数与新增文件
3. 操作耗时拆解（**必须从 `parse_timing_truth.py` 拿真实数据**）

**三者缺一不可。**

---

## 数据准确性铁律（2026-07-26 用户明确）

用户原话：
> "如果一个 report 给我的数据不是真实可靠的，随便就被你自己推翻的，那这个 report 也就没有意义了"

**规则**：
- op 维度的 count / avg / min / max / total **必须**从 `parse_timing_truth.py` 输出拿
- 不允许照抄 supervisor `各操作耗时统计:` 块
- 不允许照抄 `state/timing.json`
- 不允许"按已发笔记反推"凑数字
- 报告里如果包含 supervisor 块的数字，必须显式标注"supervisor 漏计，真实数据见下"

---

## 命名约定

- 报告文件：`/Users/tianwenliang/Documents/agent_spaces/ominicrawl/crawl_timing_YYYYMMDD.md`
  - **ominicrawl 是具体项目** → 直接放项目根（跟 README.md 同级），不建 reports/ 子分类
- 通用规则（2026-07-26 修正）：所有项目产出归 `/Users/tianwenliang/Documents/agent_spaces/<项目>/`，无项目时 fallback 到 `agent_spaces/output/`。**不要再写到 `~/.workbuddy/output/`**（那是 workbuddy 内部缓存，不是用户的项目交付目录）。

---

## 用户互动偏好

- 当用户说"文件发我"时：直接把文件 **用 `present_files` 弹出预览卡片**，不要把内容截成 `[图]` 占位贴对话里
- 用户偏好"按技术环节定位优化点"——任何报告结尾都应该给**唯一一个最值得优化的点**，不要堆数据
- 用户不喜欢冗长开场确认语——直接进入结论
- 用户要求严格"执行汇报"——做了什么、为什么、结果、待办

---

## 交互中的硬性约束

- 报告结构由 skill 锁定，不允许改动三段式顺序
- 数据源锁定 `parse_timing_truth.py`，不允许"灵活变通"用 supervisor 块凑
- 命名锁定 `crawl_timing_YYYYMMDD.md`，不允许其他命名
