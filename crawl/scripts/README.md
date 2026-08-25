# ominicrawl 脚本层（旧版说明，需配合 STRUCTURE.md 读）

> ⚠️ **本文件已部分过时**：2026-07-08 重构后，scripts/ 下 21 个 dead scripts 已被删（详见 STRUCTURE.md §9）。
> 真实架构以根目录 `STRUCTURE.md` 为准（7 月 10 日 04:10 写）。
> 本 README 仍保留：监控/单条 URL/小红书扫码这类仍活跃脚本的使用说明（它们没在 dead 清单里）。

---

# subscription-crawl 脚本层（旧版快照，仅供参考，不保证实时准确）

> `subscription-crawl` SKILL.md 的实现 — 平台分目录 + `common/` 共享层 + 调度脚本
> 重构 2026-07-08 (commit `d1baa04`) ｜ 文档维护者：闻哥 (Steven Liang)
> 本文件按「上次整理」要求**沉淀脚本使用细节**：怎么用、参数、环境变量、铁律、踩坑、限制。MEMORY.md 只保留长期事实/红线/凭证位置等不动。
> **配套文档**：整体结构与重构脉络见根目录 `STRUCTURE.md`（本 skill 的「目录树 + 命名变更 + 健壮性修复清单」静态快照）。

---

## 0. 快速索引

| 你想... | 跑这条命令 |
|---|---|
| 抓全部 3 平台 | `bash scripts/run_all.sh` 或 `bash scripts/run_all.sh all` |
| 只抓 B 站 | `bash bilibili/run.sh` |
| 只抓抖音 | `bash douyin/run.sh` |
| 只抓小红书 | `bash xiaohongshu/run.sh` 或 `bash scripts/run_all.sh xiaohongshu` |
| 单条 URL 抓取（自动识别平台） | `bash scripts/fetch_url.sh <url> [--blogger <名称>] [--inbox]` |
| 准备小红书窗口（先扫码） | `bash scripts/run_all.sh xiaohongshu-prepare` |
| 看实时进度 | `bash scripts/monitor.sh once` 或 `bash scripts/monitor.sh --loop 30` |
| 跑 XHS 9 博主全量（夜跑） | `bash /Users/tianwenliang/.agents/skills/ominicrawl/run_xhs_overnight.sh` |
| 跑 XHS 6 博主全量（旧版） | `bash /Users/tianwenliang/.agents/skills/ominicrawl/run_xhs_all6.sh` |

---

## 1. 目录与文件清单

### 1.1 根目录调度脚本 (`scripts/`)

| 文件 | 作用 | 调用方式 |
|---|---|---|
| **`run_all.sh`** | 全平台抓取总控（替代旧 `crawl_all.sh`）。**注意**：供 `monitor.sh` 识别，必须支持 `--crawl` 标志（等价 `all`） | `bash run_all.sh {all\|bilibili\|douyin\|xiaohongshu\|xiaohongshu-prepare\|--crawl}` |
| **`monitor.sh`** | 实时监控 4 平台抓取进度。`pgrep "run_all.sh --crawl"` 识别主控进程 | `bash monitor.sh once` 单次 / `bash monitor.sh --loop 30` 循环 |
| **`fetch_url.sh`** | 单条 URL 入口（自动识别 B 站/抖音/XHS/微信） | `bash fetch_url.sh <url> [--blogger <name>] [--inbox]` |
| `log_post_crawl.sh` | 抓完写台账 | 由 `run_all.sh` 自动调用 |
| `lib.sh` | 公共 shell 函数：watchlist 解析、路径、缓存、uid 提取 | 由其他 .sh `source` 引用 |
| `xhs_ocr_rapid.sh` | 小红书 RapidOCR 兜底（mmx vision 失败时回退） | 由 `xiaohongshu/ocr.py` 调用 |
| `migrate_legacy.py` | 旧数据非破坏性迁移到 `project_crawl/` | 一次性脚本（v9.2 已跑过） |
| `fetch_inbox_links.{sh,py}` | vault inbox 链接批量抓 | 手动 / cron |

### 1.2 飞书回填与修复脚本（`scripts/`）

| 文件 | 作用 | 注意事项 |
|---|---|---|
| `batch_processor.py` | 兜底扫描（处理内联失败/旧文件/OCR） | 默认 dry-run；正式写加 `--commit` |
| `gen_detail_pages.py` | 生成飞书「详情页」字段（lark-cli `--as user` 建 wiki docx） | 撞 429 自动退避；不并发 |
| `backfill_transcript.py` | 批量回填飞书「转录文字」字段（从本地 `_ocr.md` 抽 OCR 纯文本） | 默认 dry-run；`--commit` 实写 |
| `backfill_bili_transcript.py` | B 站转录回填 | 同上 |
| `backfill_wiki_links.py` | 飞书 wiki 链接回填 | 默认 dry-run |
| `backfill_detail_page.py` | 批量回填「详情页」字段 | 同上 |
| `fix_timestamp.py` | 时间戳精准修复（毫秒/秒边界） | **谨慎**：会改 frontmatter `publish_time` |
| `cleanup_callout.py` | 清理飞书 389 条 callout 脏数据 | 默认 dry-run |
| `dedup_xhs.py` | 小红书飞书去重 | 默认 dry-run |
| `delete_field.py` | 删除飞书字段 | 用于「详情链接」字段下线（v9.5.x） |
| `check_bili_transcript.py` | 检查 B 站转录完整性 | 诊断用 |
| `verify_callout_fix.py` | callout 修复验证 | 跑完 cleanup_callout 后验证 |
| `test_extract_fix.py` | `extract_sections` 修复测试 | 单测 |
| `undo_detail_page.py` | 撤销详情页写入 | 紧急回滚用 |

### 1.3 `common/` 共享模块（8 个，跨平台）

| 模块 | 关键导出 | 使用示例 |
|---|---|---|
| **`paths.py`** | `cache_file()` `notes_dir()` `media_dir()` `state_dir()` `sub_log()` `project_root()` | `from common.paths import cache_file` |
| **`util.py`** | `sanitize` `to_yymmdd` `yml_escape` `dedup` `cache_load` `cache_save` `fld` **`_parse_count`** `run_opencli` | `from common.util import _parse_count; n = _parse_count("1.5万")` |
| **`feishu.py`** | `write_feishu` `build_video_fields` | 单条写入 |
| **`batch_upload.py`** | `upload_platform` `extract_sections` | `python3 common/batch_upload.py bilibili` |
| **`llm.py`** | `summarize_md` `build_abstract` | 内联总结 |
| **`transcribe.py`** | `transcribe` `load_config` `USE_VM` | `from common.transcribe import transcribe, load_config` |
| **`fetch_log.py`** | `append_fetch_log` `_detect_share` | 写 fetch.log（Mac+VM 两端） |
| **`window.py`** | `ensure_one_window()` `close_window(wid)` | CLI: `python3 common/window.py {ensure\|close [win_id]}` |

### 1.4 平台目录（每个一致结构：`<平台>/crawl.py` + `<平台>/run.sh`）

| 平台 | 主入口 | 辅助文件 | 抓取方案 |
|---|---|---|---|
| **B 站** | `bilibili/crawl.py` | `bili_feed.py`（WBI/下载/转码）<br>`wbi.py`（签名） | B 站 API (bvid 反查) + Cookie |
| **抖音** | `douyin/crawl.py` | — | DouyinWebCrawler + a_bogus 签名 |
| **小红书** | `xiaohongshu/crawl.py` | `crawl_url.py`（单条）<br>`ocr.py`（OCR+飞书） | opencli + 真实 Chrome（副 profile `dy2s6y2k`） |
| BOSS 直聘 | `boss/fetch.py` | — | opencli |
| 领英 | `linkedin/fetch.py` | — | opencli |
| 京东 | `jd/search.py` | — | opencli jd search |
| 贴吧 | `tieba/fetch.py` | — | opencli |

---

## 2. 入口脚本用法

### 2.1 `scripts/run_all.sh`（全平台总控）

```bash
bash scripts/run_all.sh {all|bilibili|douyin|xiaohongshu|xiaohongshu-prepare|--crawl}
```

| 子命令 | 行为 |
|---|---|
| `all`（默认）/ `--crawl` | 顺序跑 B 站 → 抖音 → 小红书，每个平台抓完立即上传飞书 |
| `bilibili` / `bili` / `b` | 仅 B 站 |
| `douyin` / `dy` / `d` | 仅抖音 |
| `xiaohongshu` / `xhs` / `x` | 仅小红书（拉起副 profile → 抓 → 关窗 → 上传） |
| `xiaohongshu-prepare` / `prepare` | 仅开 XHS 窗口（让用户扫码登录），不抓取 |

**内部流程**：
1. 读 `config.yaml` 的 `USE_VM`，export 给子脚本
2. 按顺序调 `<平台>/run.sh`
3. 每个平台跑完调 `common/batch_upload.py <平台>` 上传飞书
4. XHS 走 `common/window.py ensure` 拉起副 profile（先复用自己的，再开新的）

### 2.2 `scripts/fetch_url.sh`（单条 URL 入口）

```bash
bash scripts/fetch_url.sh <url> [--blogger <name>] [--inbox] [--no-cache]
```

| 参数 | 说明 |
|---|---|
| `<url>` | 必填。自动识别：`bilibili.com`/`b23.tv`→B 站；`xiaohongshu.com`/`xhslink.com`→XHS；`douyin.com`/`iesdouyin.com`→抖音；`mp.weixin.qq.com`→微信 |
| `--blogger <name>` | 指定博主名（默认 `unknown`） |
| `--inbox` | 落到 vault `00_inbox/` 而非 `notes/<平台>/<博主>/` |
| `--no-cache` | 跳过去重缓存，强制重抓 |

**实现**：内嵌 Python 调 `common/util.py` 的 `cache_load/save` + `common/feishu.py` 写入。

### 2.3 `scripts/monitor.sh`（实时监控）

```bash
bash scripts/monitor.sh once            # 单次快照
bash scripts/monitor.sh --loop 30       # 30 秒循环（Ctrl-C 退出）
```

**监控内容**：
- 后台任务（`pgrep "run_all.sh --crawl"`）
- opencli daemon
- 4 平台缓存数量（中央 `.subscription-crawl-cache.json`）
- 磁盘 md 数量
- 最近 5 条台账（`subscription_log.md`）
- 最新 5 个抓取文件

### 2.4 平台入口 `run.sh`（B 站 / 抖音 / 小红书）

```bash
bash bilibili/run.sh
bash douyin/run.sh
bash xiaohongshu/run.sh
```

**B 站 `bilibili/run.sh`** 特有：跨博主并发 `parallel_authors`（默认 4，env `CONCURRENCY` 覆盖），FIFO 背压 `wait` 最旧。**不产 `_N` 垃圾**（v9.3 skip 修复）。

---

## 3. 配置（`config.yaml`）

```yaml
LIMIT: 10               # 每博主每次抓取条数
USE_VM: false           # true=VM 转录; false=Mac 本地转录
transcription:
  primary: local        # groq | local
  fallback: local       # groq | local | none
  parallel_authors: 4   # B 站并发; env CONCURRENCY 覆盖
summarization:
  model: glm-4-flash
  min_chars: 300
  max_body: 8000
  platforms: [bilibili, douyin, xiaohongshu]
```

### 3.1 环境变量优先级（最高 → 最低）

| 变量 | 覆盖 | 用途 |
|---|---|---|
| `OVERRIDE_LIMIT=<n>` | config.yaml `LIMIT` | 单次跑临时改抓取数（如 `OVERRIDE_LIMIT=20 bash run_all.sh douyin`） |
| `CONCURRENCY=<n>` | config.yaml `parallel_authors` | B 站并发数 |
| `USE_VM=true` | config.yaml `USE_VM` | 临时切 VM 转录 |
| `FORCE_LOCAL=1` | config.yaml `transcription.primary` | 临时绕开 Groq 走本地 |
| `OPENCLI_PROFILE=<name>` | 默认 `dy2s6y2k` | 切 opencli profile（小红书必用副 profile） |
| `GROQ_KEY=<key>` | `credentials/groq.json` | Groq API key（一般读凭证文件） |

---

## 4. 资产布局（`project_crawl/`）

所有资产收口在 `/Users/tianwenliang/.agents/skills/ominicrawl/`（可在 `config.yaml` 用 `project_root:` 覆盖）：

```
project_crawl/
├── notes/
│   ├── bilibili/<博主>/*.md            # B 站产出
│   ├── douyin/<博主>/*.md              # 抖音产出
│   ├── xiaohongshu/<博主>/*.md         # XHS 产出
│   └── wechat/*.md                     # 微信产出
├── media/                              # 图片/视频下载
├── state/
│   └── .subscription-crawl-cache.json  # 统一去重缓存（所有平台共用，按平台分桶）
├── logs/
│   ├── subscription_log.md             # 抓取台账（只此一个！）
│   ├── batch_log.md
│   └── .fetch.log                      # fetch.log（Mac 端 + VM 端）
├── credentials/
│   ├── feishu.json                     # 飞书凭证
│   └── zhipu.json
├── run_xhs_overnight.sh                # XHS 9 博主全量
└── run_xhs_all6.sh                     # XHS 6 博主全量（旧版）
```

> **博主列表（watchlist）已迁飞书**：本地 `watchlist.md` 不再使用，改读飞书文档「Watchlist 关注博主清单」（订阅Subscription 节点下，config.yaml `feishu.watchlist_doc`）。由 `common/feishu_watchlist.py` 拉取还原。

**单一收口原则**：所有本地资产（媒体/日志/state/笔记/凭证）统一在 `project_root`，不再分散在 `~/Library/Caches`、`~/.codex`、VM webdav 等处。旧 `steven_vault` 数据由 `migrate_legacy.py` 非破坏性迁至 `project_crawl`。

**凭证路径优先级**：`project_crawl/credentials/feishu.json` > `~/.agents/credentials/ominicrawl/feishu.json`（兜底）。

---

## 5. 铁律与踩坑（按脚本分组）

### 5.1 B 站（`bilibili/crawl.py` + `bili_feed.py`）

#### ⛔ 音频 403（绝对禁止）
- `upos-*.bilivideo.com` 对 **ffmpeg 内置 HTTP 客户端返回 403**（cookie/referer/origin/Range/完整浏览器头全部 403），但 `urllib.request.urlopen` / `curl` 直连均 200
- `mcdn.bilivideo.cn` 两种客户端都 200
- **根因**：upos 的 hotlink 保护针对 ffmpeg 的 HTTP 客户端签名（无 Range/HEAD/Accept 协商）
- **修复**：`bili_feed.audio_to_wav()` 用 urllib 下载到本地（`.src`）→ ffmpeg 仅做本地转码（`.wav`）。`process_video` 传入含 B 站 Cookie + 具体视频页 Referer 的请求头
- **禁止**：`ffmpeg -i https://upos-*.bilivideo.com/...` 直连。**必须** 走 urllib + 本地 ffmpeg 转码

#### skip 逻辑（v9.3 修复）
- 原 skip 仅认 `## 正文`，VM 模式（无正文）历史 md 被判未抓 → 无限重抓 + `_N` 垃圾（老张 222 md 中 183 无正文）
- v9.3 改为 `orig_md` 存在即覆盖补转录，配合有正文即 skip，**不再产生 `_N`**

#### pubdate 边界
- 必须在 `[1e9, 4.1e9]` 区间（2001-09-09 ~ 2100-01-01），越界 → `now()`（避免 1970 或离谱日期）

#### 缓存统一
- B 站 dedup 已统一到 `cache_file()`（中央 `.subscription-crawl-cache.json`）
- 旧的 `bilibili_sub.json`（split 文件）已**弃用**，本技能内不再创建

#### WBI 签名
- `bilibili/wbi.py`（原 `bili_wbi.py`）实现 WBI 签名算法；`bili_feed.py` 的 `BilibiliWbi` 类负责调用
- Cookie 来源：`credentials/bilibili.txt`

#### 并发
- `bilibili/run.sh` 默认 `parallel_authors=4` 个 `crawl.py` 进程并发，FIFO 背压 `wait` 最旧
- 用 `CONCURRENCY=2 bash bilibili/run.sh` 临时降并发

### 5.2 抖音（`douyin/crawl.py`）

#### md 章节顺序（铁律）
- 模板：`## {desc}`（第一行, H2）→ 视频链接 → `## 转录`
- `extract_sections()` 抓 summary 是第一个 `## ` 之前的内容，故**抖音 md summary 段在 `## 转录` 之前为空**（第一个 `##` 就是 `## {desc}`）
- summary 实际取自 `## 转录` 之后的速读（`common/llm.py` 在正文开头插入的 abstract）
- **禁止** 修改抖音 crawl 把 `## {desc}` 改成 `### {desc}`（会破坏速读提取）

#### LIMIT 行为
- 部分博主只拿互动最高的 10 个，**不一定是最新**（已知问题）
- 拉取走 DouyinWebCrawler + a_bogus 签名

### 5.3 小红书（`xiaohongshu/crawl.py` + `crawl_url.py` + `ocr.py`）

#### ⛔ 抓取方案铁律
- **唯一可行路线 = opencli 扩展 + 用户真实 Chrome**（`OPENCLI_PROFILE=dy2s6y2k`，`BROWSER_SESSION=xhs_main`）
- ⛔ **无头壳 / 拷贝 Profile 方案全部不可行**：
  - 无头壳 → 风控 300011（账户异常）
  - 有头拷贝 → -100（登录过期）
- **根因**：XHS 把 web_session 绑设备指纹，拷贝不同步 live 会话
- ❌ **禁止再换方案**

#### ⛔ 限流间隔（绝对遵守）
- **博主间 ≥ 3 分钟**（`run_xhs_overnight.sh` 写死 `sleep 180`）
- **限流重试 ≥ 3 分钟**（`xiaohongshu/crawl.py` 写死 `180`）
- 触发「请求太频繁」后冷却期通常数小时~1天
- 原 15s/12s 间隔太短，**必触发风控**

#### 列表抓取细节（`crawl.py fetch_user_notes`）
- JS 抽 `.cover.mask[href*="/user/profile/"]`（带 xsec），用 `__UID__` 占位 + `.replace` 绕过 Python `.format` 与 JS `{}` 冲突
- 按 `_note_id_ts`（note_id 前 8 hex = MongoDB ObjectID Unix 秒）降序 → 取前 LIMIT（**解决"抓到2月旧帖"：网格非时间序**）
- 详情 URL 必须 `/explore/<id>?xsec_token=<xsec>&xsec_source=pc_user`：
  - 无 xsec → 300031
  - `/search_result/<id>` → 300017 均不可用
- 温和滚动 ≤ 3 轮 + union 去重；够 LIMIT×1.5 或不再增长即停（防限流）
- 缓存 `.subscription-crawl-cache.json`（`project_crawl/state/`）按平台去重，中断可续跑

#### 窗口管理（`common/window.py`）
- 用法：
  - `python3 common/window.py ensure` → 复用或新开副 profile 工作窗口，返回窗口 ID
  - `python3 common/window.py close [win_id]` → 精准关闭本模块开的窗口（不动用户窗口）
- **禁止** 其他脚本直接调 Chrome 二进制（必须走此模块）
- 状态文件：`/tmp/xhs_work_win_id`（记录本模块开的窗口 ID）

#### OCR（`xiaohongshu/ocr.py`）
- 主：mmx vision describe（识别图片）
- 兜底：RapidOCR 本地识别（mmx 失败时回退）
- 调 `scripts/xhs_ocr_rapid.sh` 跑 RapidOCR
- 跑完调 `common/feishu.py --ocr` 写「正文速读」+「附件」字段

### 5.4 转录（`common/transcribe.py`）

#### 引擎优先级（v9.5.9 状态）
- config `transcription.primary: local`（已弃用 Groq 作为主）
- 链路：`mlx-whisper (Apple 神经引擎) → faster-whisper (CPU 兜底) → Groq (限流禁用)`
- mlx-whisper 0.4.3 仅 greedy 解码（不支持 beam search）
- 权重由 HuggingFace 缓存（不重复下载）
- `local.engine: mlx`, `model` 映射到 `mlx-community/whisper-<model>-mlx`

#### ⚠️ Groq 限流/挂起（历史教训）
- Groq Whisper API 间歇性 429 限流 + 单条 30-50s 慢 + 30s `_GROQ_COOLDOWN` 连锁阻塞
- 实测 mlx-whisper base 速度快 3-5 倍（单条 6-14s），无 API 限流风险
- 质量比 Groq 略低（简体/繁体偶混）但中文可用
- **回滚**（若需 Groq）：改 `config.yaml primary: groq` 或 `unset FORCE_LOCAL`

#### ⚠️ 全局变量 Gotcha（v9.5.1 教训）
- `transcribe()` 内给模块级 `_GROQ_COOLDOWN` 赋值 → Python 编译期视其为局部变量
- 读取处 `UnboundLocalError` → 所有视频转录崩溃写 0 字 md
- **`py_compile` 查不出**，必须 `global` 声明
- 验证须**端到端跑 `transcribe()` wrapper**（裸 `transcribe_mlx` 测试不会触发）
- commit `a76a632`

### 5.5 飞书写入（`common/feishu.py` + `common/batch_upload.py`）

#### 凭证与表
- APP_TOKEN: `VNLrbIYoAausDOs5uovcO7fPn0d`
- TABLE_ID: `tbljxv4cvZ5ajWWo`
- upsert 按「页面ID」（v9.5.5+ 强制）
- 凭证路径：`project_crawl/credentials/feishu.json`（优先）→ `~/.agents/credentials/ominicrawl/feishu.json`（兜底）

#### ⛔ 字段类型铁律
- **单选** = 裸字符串（如 `"B站"`），**多选** = 裸字符串列表（如 `["B站","抖音"]`）
- ❌ `{"text":"x"}` / `[{"text":"x"}]` 报 ConvFail
- ❌ 传选项内部 ID（`optXXXX`）→ 乱码（小红书 150 条曾踩此坑，v9.5.3 修复）
- ❌ `feishu_write.py` 的 `_get_opt_id()` **已在 v9.5.3 彻底删除**（取到的 option 内部 ID 写进字段会让飞书显示成乱码）

#### ⛔ 日期/时间字段必须传毫秒（v9.5.2 修复）
- 日期/时间字段 = 毫秒 int（13 位）
- 传秒 → 飞书显示 1970
- `fix_timestamp.py` 修复脚本：`scripts/fix_timestamp.py`（精准修复，谨慎使用）

#### 「详情页」 vs 「详情链接」 vs 「来源链接」
- 「**详情页**」= 飞书 wiki docx 链接（命名 `平台·博主·标题`），由 `gen_detail_pages.py`（lark-cli `--as user`）生成并回填
- state 在 `detail_pages_state.json`（821 条）
- `batch_feishu_upload` / `feishu_write` **不写**「详情页」
- 「**详情链接**」字段**已删除**（v9.5.x，与「来源链接」100% 重复，1319/1319）
- 保留「**来源链接**」

#### 飞书频控
- 等级 4：50 QPS + 1000 QPM
- 等级 21：3 QPS（慎用）
- 免费版 10000 次/月
- 触发 429/code=99991400，响应头 `x-ogw-ratelimit-reset` 退避
- 退避序列：`[5, 15, 30, 30, 60]s` 最多 5 次

#### callout 清理
- `extract_sections()` v9.5.8+ 自动剥离 Obsidian callout 语法（`>[!TYPE]` 头行 + `> ` 前缀），不再写入飞书
- 历史脏数据修复：`scripts/cleanup_callout.py` 清理 389 条 callout 残留（dry-run 验证 → commit 实写）

### 5.6 opencli（依赖）

#### 版本铁律
- ⚠️ PATH 优先 v1.7.22 vs npm 全局 `~/.npm-global/bin/opencli`（v1.8.6）
- **所有 fetch_/脚本必须用后者**（`common/util.run_opencli` 已自动选后者）
- `common/util.run_opencli()` 默认 profile `dy2s6y2k`，可 env `OPENCLI_PROFILE=<name>` 覆盖

#### 工具子命令
- `opencli doctor` — 检查扩展连接（输出 `Extension: connected` 才算 OK）
- `opencli xiaohongshu user-notes` — 抓博主列表
- `opencli boss detail <id>` — Boss 详情
- `opencli boss` 的输出**可能为 JSON array 或 object**，也可能为空/非 JSON
- ❌ **禁止** 裸 `json.loads(r.stdout)`，用 `common/feishu.py` 或 `boss/fetch.py` 的防御性解析

### 5.7 依赖 / 运行时

- Python: 优先 `/Users/tianwenliang/.codex/binaries/python/versions/3.13.12/bin/python3`
- httpx 必须 `<0.28`（与 B 站/抖音 WBI 签名兼容）
- ffmpeg：必须本地转码（`/opt/homebrew/bin/ffmpeg`），**禁止 ffmpeg 直连 upos**
- mlx-whisper：仅 Apple Silicon (M1/M2/M3/M4)

### 5.8 第三方平台（BOSS / LinkedIn / 京东 / 贴吧）

- 全部走 `opencli` 驱动
- **BOSS / LinkedIn ephemeral 模式每日上限 30 条**
- 微信单条 URL 由 `scripts/fetch_url.sh` 自动识别处理

---

## 6. 限制与已知问题

| 项目 | 限制 / 已知问题 |
|---|---|
| 抖音 | 部分博主只拿互动最高的 10 个，不一定是最新 |
| 小红书 | opencli 兜底，需真实 Chrome（dy2s6y2k 副 profile）；cookie 7-30 天过期 |
| BOSS / LinkedIn | ephemeral 模式每日上限 30 条 |
| 飞书免费版 | 10000 次/月 |
| 抖音 LIMIT 优先级 | 环境变量 `OVERRIDE_LIMIT` > config `LIMIT` > 默认 10 |
| B站并发 | 默认 4（env `CONCURRENCY` 覆盖） |
| XHS 限流 | 触发后冷却期数小时~1天，**不要反复重跑**加重风控 |

---

## 7. 维护铁律

1. **命名**：禁止 `v2`/`v3` 版本号；统一 `<平台名>+<职责>.py`（如 `bilibili/crawl.py`）
2. **共享**：跨平台工具统一 `from common.util import ...`，**禁止本地副本**
3. **缓存**：所有平台共用 `cache_file()`，**禁止 split 文件**（`bilibili_sub.json` 已弃用）
4. **B 站音频**：禁止 ffmpeg 直连 `upos-*.bilivideo.com`（必 403），必须 urllib + 本地转码
5. **中文数字**：禁止裸 `int(likes)`，统一用 `_parse_count()` 兜底（返回 0 而非崩溃）
6. **XHS 抓取**：仅走 `opencli` + 用户真实 Chrome（`dy2s6y2k` 副 profile），禁止无头/拷贝方案
7. **窗口管理**：通过 `common/window.py ensure` 子命令（不允许其他脚本直接开 Chrome）
8. **全局变量**：模块级可变状态赋值前必须 `global` 声明（v9.5.1 教训）
9. **日期字段**：飞书必传毫秒（13 位 int），禁止传秒（→ 1970）
10. **选项字段**：飞书必传裸字符串/列表，禁止传 `{"text":...}` 或 `optXXXX` 内部 ID

---

## 8. 故障排查 Checklist

| 症状 | 排查 |
|---|---|
| XHS 「请求太频繁」 | 博主间已 180s? 重试已 180s? IP 是否已冷却? → 查 `/tmp/xhs_crawl.log` |
| B 站音频下载 403 | 是否走 `bili_feed.audio_to_wav`? 是否用 urllib（不是 ffmpeg）? |
| 飞书写入 429 | 频控触发？退避序列 `[5,15,30,30,60]s` 最多 5 次 |
| 飞书日期显示 1970 | 字段传了秒？用 `fix_timestamp.py` 修 |
| 飞书选项乱码 | 是不是传了 `optXXXX`? 改回裸字符串 |
| 转录崩溃 0 字 | `_GROQ_COOLDOWN` 有没有 `global` 声明? 跑端到端 transcribe 验证 |
| 抓不到小红书 7/7 新帖 | 缓存是否已含 7/7? 限流是否解封? `OVERRIDE_LIMIT` 是否够大? |
| 重复抓（`_N` 垃圾） | B站 VM 模式？升级 v9.3 skip 逻辑 |
| 飞书多维表格 callout 脏数据 | 跑 `cleanup_callout.py` dry-run → commit |

---

*本文件由 2026-07-08 重构 (commit d1baa04) 落地；上次整理结论：脚本使用细节应沉淀到 README 而非 MEMORY。MEMORY.md 仅保留长期事实/红线/凭证位置。*
