# CHANGELOG — crawl skill

## 3.1.0 (2026-08-11) — B站/抖音 转录迁移到 VM

**背景**：Groq 对中国大陆 IP 永久 403（与 VPN 无关），B站/抖音转录长期失效。

**改动**：
- 新增 `tools/handoff_vm.py`：Mac→VM 音频交接（rsync over SSH 免密 + 构造 `meta.json`）。
- `ingest-bilibili/bilibili.py` / `ingest-douyin/douyin.py`：新增 `vm.asr_routing` 开关；开启后下载完音频即 handoff 到 VM，返回 `md=None` 让 `pipeline/run.py` 跳过本地转录与总结（pipeline 零改动）。
- `config.yaml`：新增 `vm:` 段（`asr_routing` / `crawl_transcribe_inbox` / `share`），`asr_routing` 默认 `true`。
- VM 端（部署于 `175.178.210.156:/home/ubuntu/crawl-transcribe/`）：
  - `transcribe_daemon.py` — systemd 服务 `crawl-transcribe` 常驻，30s 轮询 `inbox/`，串行 转录→总结→发布，删源 + 回执 `crawl_op_vm_YYYYMMDD.md`。
  - `transcribe_worker.py` — FunASR(Paraformer+VAD+PUNC) 转录 + Zhipu GLM(glm-4-flash) 总结 + `publish_vault.append_single_to_hot` 写 vault。
  - `publish_vault.py` — 复用 Mac 侧发布逻辑，VAULT 走环境变量。
- 新增 `~/Documents/agent_spaces/ominicrawl/backfill_pending_vm.py`：积压 `state/pending_audio/bilibili/*.wav` 补元数据后批量回填 VM。

**验收**：2026-08-11 单条端到端测通（72s：模型加载+转录+Zhipu 总结+发布，源音频已删，回执正确）。

### 3.1.0 hotfix (2026-08-11 17:55) — 修复笔记缺转录 / 重复

**症状**：积压 28 个音频 VM 处理"成功"但 vault 笔记无逐字转录（双份：空壳 `.md` + 满版 `_1.md`，段名 `## 转录全文` 与检查脚本预期的 `## 转录` 不匹配）。

**根因**：① VM worker 旧版段名 `## 转录全文`/`## AI 总结` 且与空壳同名时序号化为 `_1.md` 而非覆盖；② Mac crawler 在 handoff 模式仍落空壳 md。

**改动**：
- VM `transcribe_worker.py`：段名归一 `## 描述`/`## 转录`/`## 总结`，补 `## 描述`（meta.desc）。
- VM `publish_vault.py`（VM 独立副本）：`_write_author_file` 改为覆盖而非序号化 `_1.md`。
- 新增 `fixup_merge_worker_notes.py`：合并 27 个 `_N.md` 满版回 base.md + 段名归一。
- Mac `bilibili.py`/`douyin.py`：handoff 时把 `desc` 写入 meta.json（影响未来抓取）。
- VM daemon 重启到干净状态。

### 3.1.0 hotfix2 (2026-08-11 18:10) — 删除 Groq 回退，VM 成为唯一 ASR 路径

**诉求**：闻哥要求"把回退删掉，只保留通过 VM 进行 ASR 转录作为唯一路径"。

**改动**：
- `ingest-bilibili/bilibili.py` / `ingest-douyin/douyin.py`：彻底删除本地 Groq 转录分支（`transcribe()` / `[ASR.FATAL]` 回退 / `## 预览片段` 逻辑）。`vm_routing_enabled` 开启时 handoff 到 VM；**上传失败 → `[HANDOFF.FAIL]` 持久化 wav 供 backfill 重试并跳过，不再尝试 Groq**；`vm_asr_routing=false` → `[ASR.OFF]` 直接跳过（本地 ASR 已停用）。
- 删除两个 fetcher 对 `common.transcribe` 的 import（`transcribe`/`get_audio_duration`/`apply_transcript` 不再使用）。
- `config.yaml`：`transcription.engine: groq` 标注为对 bilibili/douyin 已不再调用的遗留配置。

**核验**：`py_compile` 通过；经 shim `exec_module` 加载两个活文件无 `NameError`；全仓库 grep 确认 bilibili/douyin 活代码已无任何 Groq / 在线 ASR 调用（仅 docstring 提及，无执行路径）。

**注**：`ingest-bilibili/bilibili/crawl.py` 与 `ingest-douyin/douyin/crawl.py` 为旧副本，运行时由 `tools/*.py` shim 加载 `ingest-*/{platform}.py`，嵌套 `crawl.py` 不被任何模块 import，属死代码（含 Groq 引用但不影响行为）。


**核验**：27/27 bvid 笔记含 `## 转录`，`## 转录全文`/`## AI 总结` 残留 0。

### 3.1.0 hotfix3 (2026-08-11 19:40) — 修复 总结 段顺序（在转录后面 → 在前面）

**症状**：0810-index 等 VM 转录笔记中，`## 总结` 被放在 `## 转录` 之后（正文后面），与原始设计不符。

**根因**：VM `transcribe_worker.py` 自己拼笔记时写成 `## 描述 / ## 转录 / ## 总结`，
把 `## 总结` 放到末尾。但原始契约（`common-summary/summarize.py` 的 `inject_summary_to_md` /
`migrate_summary_to_abstract`、以及 `summarize_markdown.py` 的 abstract 区约定）要求 `## 总结`
位于 **abstract 区（frontmatter 之后、第一个内容 H2 之前）**，即总结在前、转录在后。
末尾总结会被 `build_note_block()` 当作 transcript 区屏蔽，推飞书时拿不到 🎯/⏳/💡。

**改动**：
- VM `transcribe_worker.py`（Mac 源 `_vm_transcribe_worker.py`）：段顺序改为
  `## 总结 / ## 描述 (abstract 区, 在前) → ## 转录 (在后)`。已 rsync 到 VM。
- 新增 `~/Documents/agent_spaces/ominicrawl/fixup_summary_order.py`：把 `## 总结` 是文件
  最后一个 H2 的笔记（worker 误写末尾的产出）挪回 abstract 区。仅作用于此类笔记，
  不动历史正确笔记。本地 vault + VM WebDAV vault 双端各跑一遍。

**核验**：本地 + VM 各迁移 35 篇（含 0810 全部 27 篇及 6 月底以来 VM 产出）；
全仓 825 篇转录笔记，`## 总结` 在 `## 转录` 之后的 = 0。
遗留 8 篇更早的「无 `## 转录` 旧格式笔记」（6月底~7月遗留爬取）`## 总结` 仍在末尾，
属另一类旧格式，不在本次转录 bug 范围内（待闻哥决定是否一起挪前）。

### 3.1.0 hotfix4 (2026-08-11 20:05) — 修复 backfill 旧路径硬编码 Groq

**症状**：`run.sh all` 在 supervisor Step 0.5 自动跑 `tools/backfill_pending.py`，扫 `state/pending_audio/{bilibili,douyin}/` 用**本地 Groq 转录**补历史 wav；VM 成为唯一 ASR 路径后，这些 wav 全部 HTTP 403 失败，每次跑批留 6~12 个 wav 污染 `pending_audio`。

**根因**：3.1.0 删 fetcher 的 Groq 分支时漏改了 backfill 工具（旧路径残留）。

**改动**：`tools/backfill_pending.py` 的 `process_one` 不再本地 Groq 转录，改为与 fetcher 一致走 VM：
- md 已转录(>100字)：wav 冗余，直接删。
- md 空正文：提取 frontmatter meta → `handoff_to_vm()` 上传 VM 异步补转录 → 成功后删本地 wav。
- 新增 `extract_meta_from_md()` 从 md frontmatter 提取 title/author/source_url/publish_date 供 handoff。

**验证**：实际运行 12/12 成功（6 冗余删 + 6 空正文 handoff VM）；`pending_audio` 清空；下次 `run.sh all` Step 0.5 将显示「待 backfill: 0 个」。

### 3.1.0 hotfix5 (2026-08-11 22:14) — OP 报告合并对齐 VM 异步转录
- generate_op_report.py 新增 parse_vm_report()：读取 VM 端回执 `crawl_op_vm_<date>.md`，提取本批转录篇数 / 按平台累计耗时 / 处理窗口
- 「按 OP 统计」Groq 转录（已废弃旧口径，写死"未记录"）改为 VM 转录（异步标注，不计入本地墙钟）
- 「本批输出」口径修正：本地落库 N + handoff VM M（不再把 VM 当天总量 58 冒充本次产出；VM 58 注明含历史 backfill，置于新增第五节）
- 新增「五、VM 异步转录阶段」小节：累计处理耗时（89.0min）+ 墙钟跨度（179.1min），与本地墙钟 7.2min 不闭合说明

### 3.1.0 hotfix6 (2026-08-12) — 去重完整性检查（根治空壳永久跳过）

**症状**：部分视频笔记只有 frontmatter + 标题，没有 `## 转录`/`## 总结` 正文（如 0811 批次 4 个抖音视频）。

**根因**：`common-flow/crawl.py` 的去重只看 `cache`（视频 id 列表）。空壳笔记（有 frontmatter 无转录）一旦写入 cache，下次 run 判"已缓存"永久跳过，永不 handoff VM 补转录。

**改动**：`common-flow/crawl.py`
- 新增 `_extract_vid_from_url()` / `_ensure_vid_index()` / `_md_is_complete()`。
- 去重分支：视频平台(bilibili/douyin)需该 vid 的 md 存在且有 `## 转录` 才算"已处理"；否则清 cache 记录并重处理（落到 `process_url` → handoff VM 补转录）。
- 索引 run 内懒加载一次（扫 `subscription/<plat>/` 建 `{vid: 有##转录}`），性能可控。
- 非视频平台(xiaohongshu/tieba/jd 等)保持原 cache 行为。

**验证**：0811 那 4 个空壳抖音已移入 Trash；重新 `run.sh all` 触发重抓 → handoff VM 补转录。以后偶发空壳也会在下个 run 自动自愈。

### hotfix7 (2026-08-12) — VM 发布后自动重写当日 index
- **根因**：本地 `run.sh all` 在 VM 异步转录完成**之前**就生成 `MMDD-index.md`，VM 之后落地的视频笔记从未被加入 index → index 不全（0811 实测缺 9 篇 B站/抖音视频）。
- VM 端 `publish_vault.append_single_to_hot` 写文件后新增 `_regenerate_daily_index()`，基于 WebDAV vault 现状重建当日 index（覆盖式，单一真相源），保证 index 与 vault 始终一致。
- `common-today/gen_today.py` 支持 `VAULT` 环境变量（默认 Mac 路径，VM 端覆盖为 WebDAV vault），Mac/VM 共用同一份聚合逻辑。
- 已部署：rsync `gen_today.py` + 新 `publish_vault.py` → VM `/home/ubuntu/crawl-transcribe/`。
- **验证**：VM 端调用无异常，0811-index 重建为 40 篇（含 VM 异步落地笔记）；历史缺失已用 gen_today 全量补全。以后每次 VM 发布自动自愈，无需手动。

## 3.0.0 (2026-07-30) — ASR 极简模式

- `transcribe()` 仅走 Groq；Bailian/MLX/Tencent 函数保留默认不调用，无需刷新它们的凭证。
- Groq 失败 → `raise RuntimeError` → caller catch + `[ASR.FATAL]` 跳过该条。
- 详见 `git log`。
