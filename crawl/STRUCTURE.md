# ominicrawl 程序文件结构说明 (v1, 2026-07-10 重写)

> 取代 2026-07-08 subscription-crawl 快照，反映当前真实架构（多入口 + 工具层 + 流水线 + 共享模块）。
> 根目录：`~/.agents/skills/ominicrawl/`
> **配套文档**：`SKILL.md`（触发词/平台契约/铁律）+ `scripts/README.md`（脚本参数）。
> **维护原则**：新增/删除/重命名/跨层复用 → 同步更新本文件。

---

## 一、设计总览（3 层 + 共享底座）

```
┌─────────────────────────────────────────────────────────────┐
│ 入口层 (crawl.py / shell 脚本)                                │
│   - 来源编排: clip / watchlist / url / set-tool                 │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 工具层 (tools/<platform>.py)                                  │
│   - 9 个 fetcher: 每个平台一个文件, 契约统一                     │
│   - URL型 5 个 (crawl(url, tmp))                             │
│   - 搜索型 4 个 (crawl_batch(date))                          │
│   - 切换由 registry + config.yaml tools: 驱动                  │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 流水线层 (pipeline/run.py)                                    │
│   - process_url(URL 型): 抓 → 推 → 总结                        │
│   - process_search(搜索型): 批量抓 → 推(无总结)                │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 共享底座 (common/*.py + lib/douyin_api/)                       │
│   - opencli_bridge / registry / push_to_feishu /                │
│     summarize / transcribe / clipboard / feishu_watchlist /   │
│     paths / util / window / summarize_markdown / llm(退役)    │
│   - lib/douyin_api: 抖音/B站 crawler 库 (底层)                 │
└─────────────────────────────────────────────────────────────┘
```

**单一真相源**：
- 配置：`config.yaml`（`feishu_dest` 飞书节点 / `tools:` 平台工具 / `opencli:` 浏览器桥 / `transcription` 转录策略）
- 凭证：`~/.agents/credentials/ominicrawl/{feishu,zhipu,groq}.json`

---

## 二、完整目录树

```
ominicrawl/
├── SKILL.md                          # 触发词/工作流/平台契约/铁律
├── STRUCTURE.md                      # 本文件 (整体架构)
├── config.yaml                       # 真相源 (feishu_dest / tools / opencli / transcription)
├── crawl.py                          # ★ 入口层 — 来源编排 (clip/watchlist/url/set-tool)
├── DOUYIN_WATCHLIST_2026-07-10.md    # 早期 故障排查文档
│
├── common/                           # 共享底座
│   ├── __init__.py
│   ├── clipboard.py                  # 入口层依赖: Apple 备忘录剪藏队列 (read/extract/remove/canonical_key)
│   ├── registry.py                   # 工具层依赖: 平台 → 工具路由 (get_tool/is_enabled/can_monitor/set_tool)
│   ├── opencli_bridge.py             # 跨层底座: 浏览器桥接 (ensure_connected/tab/extract/run_adapter/fetch_rendered)
│   ├── push_to_feishu.py             # 流水线层依赖: 推 docx (push 单篇 / push_aggregated 聚合 ★ 含章节拼装)
│   ├── summarize_markdown.py         # 流水线层依赖: md → 章节 (parse_frontmatter/extract_sections/build_note_block/render_note_markdown)
│   ├── summarize.py                  # 流水线层依赖: GLM-4-flash 主题-bullet 总结 (主题-bullet 总结协议)
│   ├── transcribe.py                 # 工具层依赖: 本地 mlx-whisper → Groq 兜底 (Groq 限流后自动本地)
│   ├── feishu_watchlist.py           # 入口层依赖: 飞书 Watchlist 文档 → markdown 表格 (10min TTL 缓存)
│   ├── feishu.py                     # 28K 历史单条飞书写入 (被 push_to_feishu 大部分替代, 含旧 push_to_feishu 接口)
│   ├── batch_upload.py               # 飞书批量上传 (历史, pipeline 已不依赖)
│   ├── llm.py                        # 旧 LLM 总结 (被 common/summarize.py 替代, 仍保留作为 backup)
│   ├── util.py                       # 工具函数 (sanitize/slugify/_parse_count/run_opencli_json + NO_PROXY 注入)
│   ├── paths.py                      # 路径中枢 (project_root/notes_dir/cache_file/media_dir/credentials_dir)
│   ├── window.py                     # XHS 副 profile 窗口管理 (ensure_one_window/close_window, 仅 XHS 用)
│   ├── fetch_log.py                  # 抓取台账 (Mac+VM 共享, 历史)
│   └── crawl_log.py                  # 同上 (新版本, 重复, 处于半退役)
│
├── pipeline/                         # 流水线层
│   ├── __init__.py
│   └── run.py                        # ★ 编排器 (process_url / process_search + 平台分类字典)
│
├── tools/                            # 工具层 (9 个 fetcher)
│   ├── __init__.py
│   ├── _search_common.py             # 搜索型 4 平台公用 (slugify/mmdd/search_opencli/write_md)
│   ├── _wechat_kernel_main.py        # 微信内核 (脱壳自 my-wechat-spider, 独立 .py 不依赖外部 skill)
│   ├── bilibili.py                   # URL 型 — BilibiliWebCrawler + 转录 (crawl 契约)
│   ├── douyin.py                     # URL 型 — DouyinWebCrawler + 转录 (crawl 契约)
│   ├── xiaohongshu.py                # URL 型 — 调 xhs-downloader/single_extract.py (crawl 契约)
│   ├── generic.py                    # URL 型 — trafilatura + opencli 兜底 (知乎反爬) (crawl 契约)
│   ├── wechat.py                     # URL 型 — 调 _wechat_kernel_main.py (crawl 契约)
│   ├── boss.py                       # 搜索型 — opencli boss search (crawl_batch 契约)
│   ├── jd.py                         # 搜索型 — opencli jd search
│   ├── linkedin.py                   # 搜索型 — opencli linkedin search + browser extract 兜底
│   └── tieba.py                      # 搜索型 — opencli tieba search
│
├── bilibili/                         # 历史平台独立入口 (脚本可单独跑, 工具层复用其 bili_feed/wbi/crawler)
│   ├── crawl.py                      # 博主级抓取 (并发, USE_VM)
│   ├── bili_feed.py                  # WBI 签名/音频下载/转码
│   ├── wbi.py                        # WBI 签名算法
│   └── run.sh                        # 平台入口脚本
├── douyin/                           # 历史 — 工具层复用其 lib (douyin_api)
│   ├── crawl.py                      # 博主级抓取
│   └── run.sh
├── xiaohongshu/                      # 历史
│   ├── crawl.py crawl_url.py ocr.py run.sh
├── boss/   linkedin/  jd/   tieba/   # 历史 (scripts/run_all.sh 走这些旧入口)
│   └── fetch.py / search.py
│
├── lib/douyin_api/                   # ★ 底层抖音/B站 crawler 库 (Douyin_TikTok_Download_API)
│   ├── crawlers/
│   │   ├── base_crawler.py
│   │   ├── utils/                    # logger/api_exceptions/utils
│   │   ├── bilibili/web/             # BilibiliWebCrawler + config/endpoints/wbi/models/wrid
│   │   └── douyin/web/               # DouyinWebCrawler + config/abogus/xbogus/endpoints/models
│
├── state/                            # 运行时数据 (不提交)
│   ├── .watchlist_feishu_cache.md    # 10min TTL 缓存
│   └── clip_cache.json               # 剪藏模式去重
│
├── scripts/                          # ⚠️ 混合区 — 含历史脚本 + 新脚本, 详见第七节
│   ├── README.md                     # 脚本使用细节
│   ├── run_all.sh                    # 历史总控 (订阅式旧 skills 调用, 新工具用 crawl.py watchlist)
│   ├── publish_wiki.py              # 历史 publish_wiki (28K, 复制自 subscription-crawl, ⚠️ 当前未使用)
│   ├── push_to_feishu.py             # 历史推送 (废弃, 改用 common/push_to_feishu.py)
│   ├── fetch_url.sh                  # 历史单条入口 (废弃)
│   ├── fetch_inbox_links.{sh,py}    # 邮件/笔记入口 (旧, deprecated)
│   ├── publish_wiki.py               # 旧 publish (deprecated)
│   ├── platforms/                    # 复制自 link-crawl, ⚠️ 实质未使用, 5 个平台都被 tools/* 替代
│   │   ├── bilibili.py douyin.py generic.py wechat.py xiaohongshu.py
│   ├── link_crawl.py                 # link-crawl 旧入口 (deprecated)
│   ├── summarize.py                  # link-crawl 旧总结 (deprecated, 改为 common/summarize.py)
│   ├── monitor.sh                    # run_all.sh 监控 (旧)
│   ├── batch_processor.py            # 旧 batch 兜底
│   ├── backfill_*.py (5 个)          # 旧 backlog 回填工具 (deprecated)
│   ├── cleanup_callout.py dedup_xhs.py delete_field.py fix_timestamp.py
│   │   gen_detail_pages.py migrate_legacy.py verify_callout_fix.py
│   │   test_extract_fix.py undo_detail_page.py fetch_inbox_links.{sh,py}
│   │   log_post_crawl.sh xhs_ocr_rapid.sh lib.sh cache.json
```

---

## 三、3 层职责详解

### 3.1 入口层 (`crawl.py`)

| 子命令 | 路由 |
|---|---|
| `crawl url <URL>` | URL → detect_platform → process_url(clip mode) |
| `crawl clip` | 读 Apple 备忘录剪藏队列 → 逐条 process_url |
| `crawl watchlist [--date YYYYMMDD] [--platform ...]` | 1) 读飞书 Watchlist (10min TTL) → 2) 搜索型平台跑 process_search → 3) bilibili/douyin 跑 expand-then-crawl → 4) 落入 KYIT 聚合 docx |
| `crawl set-tool <平台> <工具>` | 写回 config.yaml tools: 区段 |
| `crawl tools` | 打印 平台→工具 映射 |

**关键约定**：watchlist 是爬批入口，单条 url 是剪藏入口；两者共享相同 `tools/<p>.crawl` 契约但走不同流水线。

### 3.2 工具层 (`tools/<p>.py`, 9 个 fetcher)

**统一契约**（两个形态）：

```python
# URL 型 (5 个: bilibili/douyin/xiaohongshu/wechat/generic)
def crawl(url, tmp_dir, timeout=...) -> (title, author, md_path, images_dir)

# 搜索型 (4 个: boss/jd/linkedin/tieba)
def crawl_batch(date_yymmdd=None) -> [(title, author, md_path, None), ...]
```

**反例**：3 元素 vs 4 元素 → `process_url` 已宽容两者。

**平台 → 工具映射**（`config.yaml` tools: 真相源）：

| 平台 | fetcher | 默认工具 |
|---|---|---|
| bilibili  | tools/bilibili.py | subscription-fetcher (Pure lib + 转录) |
| douyin    | tools/douyin.py | 同上 |
| xiaohongshu | tools/xiaohongshu.py | xhs-downloader (外部 skill 调用) |
| generic (web) | tools/generic.py | trafilatura + opencli 反爬兜底 |
| wechat    | tools/wechat.py | wechat-fetcher (= 内核化 main.py) |
| boss / jd / linkedin / tieba | tools/{boss,jd,linkedin,tieba}.py | scrapling (opencli 原生适配器) |

**禁用占位**：`opencli-xhs` / `markitdown` 已注册但 enabled=false，**切配置即生效不写代码**。

### 3.3 流水线层 (`pipeline/run.py`)

```
                        detect_platform(url)
                              │
                              ▼
                ┌───────────────────────────────┐
                │  is_enabled(plat)?             │── no ─→ skip
                │  can_monitor(plat) (watchlist) │
                └───────────────────────────────┘
                              │ yes
                              ▼
                  ┌──────────────────────────┐
                  │ tools/<plat>.crawl/batch │
                  │   (抓 + 转录 + ocr 可选) │
                  └──────────┬──────────────┘
                             ▼
                ┌────────────────────────────┐
                │  push(单篇 IN4R)            │
                │  push_aggregated(聚合 KYIT)  │
                └──────────┬─────────────────┘
                           ▼
                ┌────────────────────────────┐
                │  plat ∈ SUMMARIZE_PLATFORMS │
                │  ? _summarize_and_insert()  │
                └────────────────────────────┘
```

**`SUMMARIZE_PLATFORMS = {bilibili, douyin, xiaohongshu, generic}`**：4 个会调 GLM-4-flash 总结；boss/jd/li/tieba/wechat 仅推原始单文件。

**`URL_PLATFORMS = {bilibili, douyin, xiaohongshu, generic, wechat}`**：接受 `crawl url` 命令。

**`SEARCH_PLATFORMS = {boss, jd, linkedin, tieba}`**：走 `crawl_batch(date)`。

### 3.4 共享底座 (`common/`)

| 模块 | 关键导出 | 谁依赖 |
|---|---|---|
| `clipboard` | read_clip_text / extract_urls / remove_url_from_note / canonical_key | 入口层 (clip) |
| `registry` | get_tool / is_enabled / can_monitor / set_tool / show_tools | 工具层 + 流水线层 |
| `opencli_bridge` | ensure_connected / tab / extract / run_adapter / fetch_rendered | 工具层 (generic 反爬) |
| `push_to_feishu` | push (单篇) / push_aggregated (聚合) / lark 子进程 / _find_child | 流水线层 |
| `summarize_markdown` | build_note_block / render_note_markdown (从订阅脚本移植) | push_to_feishu / 流水线层 |
| `summarize` | summarize(md_path) → JSON (主题-bullet 总结协议) | 流水线层 |
| `transcribe` | transcribe(source_url) → (text, source) (Groq → mlx → faster_whisper) | 工具层 (bilibili/douyin) |
| `feishu_watchlist` | get_watchlist_markdown / parse_rows / get_boss_keywords 等 | 入口层 (watchlist) |
| `paths` | project_root / notes_dir / cache_file / media_dir / credentials_dir | 全栈 |
| `util` | sanitize / slugify / run_opencli_json (6 次重试 + NO_PROXY) | 工具层 (通用) |
| `window` | ensure_one_window / close_window (XHS 副 profile Chrome 单独跑) | (历史) |
| `feishu` | write_feishu 等 (历史单条接口, push_to_feishu 大部分替代) | (历史) |
| `llm` | (历史) 仍可作 fallback | (历史) |

---

## 四、调用链（典型路径）

### 4.1 单条 URL 剪藏
```
bash crawl.py url "https://..."
  ↓
crawl.py.cmd_url()
  ↓
pipeline.process_url(url, {mode: "clip"})
  ├─ detect_platform(url)
  ├─ tools/<plat>.crawl(url, tmp_dir)        # 写 md + images 到本地
  ├─ common.push_to_feishu.push(md, ...)       # 建单篇 docx 到 IN4R
  └─ _summarize_and_insert(obj, md) (可选)
```

### 4.2 Watchlist 夜跑（核心长路径）
```
bash crawl.py watchlist --date 20260709
  ↓
crawl.py.cmd_watchlist(date)
  ├─ common.feishu_watchlist.get_watchlist_markdown()
  │    ├─ 缓存 hit (10min TTL) → 读 state/.watchlist_feishu_cache.md
  │    └─ miss → lark-cli docs +fetch --doc UWvidt2... → 解析 → 缓存
  │
  ├─ [搜索型 4 家] for plat in (boss, jd, linkedin, tieba):
  │    └─ pipeline.process_search(plat, date)
  │         ├─ tools/<plat>.crawl_batch(date)     # 写每关键词一个 md
  │         └─ common.push_to_feishu.push_aggregated  # 追加到 KYIT 聚合 docx
  │
  └─ [URL 型博主 2 家] for plat in (bilibili, douyin):
       ├─ _extract_<plat>_id(url)            # mid / sec_uid
       ├─ _list_<plat>_videos(suid, limit)     # 枚举博主最新视频 URL
       ├─ for v in vids (去重 cache):
       │    └─ pipeline.process_url(v, {mode: "watchlist", date})  # 同 4.1
       └─ cache_save(cache)                    # 更新去重缓存
```

### 4.3 单个 fetcher 内部（典型：B站）
```
tools/bilibili.py.crawl(url, tmp_dir)
  ├─ extract_bvid(url) / resolve_short_url(b23.tv)
  ├─ asyncio.run(process_one(bvid, tmp_dir))
  │    ├─ BilibiliWebCrawler.fetch_one_video(bvid)   # 元数据
  │    ├─ BilibiliWebCrawler.fetch_video_playurl()  # 音频流
  │    ├─ audio_to_wav() → wav 文件
  │    ├─ common.transcribe.transcribe(wav)         # Groq/mlx 转录
  │    └─ 写 md + frontmatter
  └─ return (title, author, md, None)
```

---

## 五、铁律（架构强约束）

1. **fetcher 只能写本地 md + images**，**不直接调飞书 API**。推到飞书统一走 pipeline → push_to_feishu。
2. **`canonical_key` 是 dedup 的唯一身份**：URL 上的 `?...&spm=` 不参与去重。
3. **同一进程内同一 (date·platform) 复用同一篇聚合 docx**：push_to_feishu 的 `_agg_cache`。
4. **章节结构只推一次**：H1=博主/H2=文章/H3=要点。博主首次出现写 H1，后续该博主视频只写 H2+H3。
5. **`cache_load()` 只更新去重**，**不写飞书**。飞书落点是 cron 跑批外的独立维度。
6. **搜索型平台不调总结**（boss/jd/li/tieba：信息量小，原始抓取即够）。
7. **转录失败不阻塞抓取**：`tools/<p>.crawl` 落元数据后返回，pipeline 静默总结失败。
8. **daemon 不自动重启**（断开浏览器桥扩展）；跑批前人工/启动脚本做一次 NO_PROXY 重启。
9. **watchlist 缓存 TTL = 10min**——用户在飞书改关键词最多 10min 内生效。

---

## 六、已知问题清单（结构级 bug，与运行时 bug 分开）

### 6.1 文档与代码不一致
- **SKILL.md / STRUCTURE.md 描述的是 v3 设计**（3 来源 2 来源/工具层/流水线），但实际目录已落到 v1（你在用的）：`tools/<p>.crawl` 而不是 `tools/<p>.crawl_batch`(boss 等 4 家是 crawl_batch, 文档没说明白)。
- **写工具实现的 hyperlink/章节契约**未在 SKILL.md 体现（只列了触发词）。

### 6.2 Dead code (历史包袱)
- **`scripts/publish_wiki.py`** (28K) 复制自 subscription-crawl，**当前 pipeline.run 没用它**，整合时该删。
- **`scripts/platforms/`** (5 个文件) 复制自 link-crawl，**当前 tools/* 替代了所有功能**，0 引用。
- **`scripts/run_all.sh`** 仍是订阅式入控，**新入口 crawl.py 独立**——两套并存让新人不知道哪个是当前入口。
- **`scripts/{fetch_url,link_crawl,backfill_*,dedup_xhs,fetch_inbox_links,fix_timestamp,delete_field,gen_detail_pages,...}`** 一系列脚本 0 引用，历史产物。
- **`common/feishu.py` (28K)** 含 `write_feishu` 等历史单条接口，push_to_feishu 大部分替代了，但仍被 common/push_to_feishu.py 内部用 `_find_child` 等辅助功能。
- **`common/llm.py`** vs `common/summarize.py`：两个 LLM 总结实现并存；summarize.py 是新版本。

### 6.3 复用与契约错位
- **平台层（bilibili/douyin/douyin/douyin/boss/jd/linkedin/tieba/）** 还活在根目录，跟 tools/* 提供同样功能，**契约不同**：bilibili/run.sh 调 bilibili/crawl.py 传 mid+name+out_dir 而 tools/bilibili.py 调 crawl(url,tmp) → **两套不能直接互调**。run_all.sh 仍用根目录的旧版，意味着你跑 `bash scripts/run_all.sh` 走的是**已退役的** v3 流水线。
- **fetch_url.sh 同时存在两份**：scripts/fetch_url.sh（旧 url mode）+ tools/generic.py（新版 url 模式）。前者用 osascript/curl，后用 trafilatura+opencli。
- **run.sh 脚本过于分散**：每个平台目录下一份 (bilibili/run.sh, douyin/run.sh, xiaohongshu/run.sh)，invoke 自己目录的 fetch.py 而非 tools/。**基本没人用了**——如果删了，脚本层会干净很多。

### 6.4 配置重复
- **`feishu_dest` / `opencli` / `transcription` 在 config.yaml 一处定义**（✓ 这个正确）。
- **但 `feishu_dest.clip_parent` 默认值在 push_to_feishu.py:35 又写死一次**（没读 config? 已读，但 fallback 走了默认值，默认值应当是兜底而不是真理源）。
- **平台默认工具散落 3 处**：config.yaml + tools/registry 推断 + (omitted) 历史脚本逻辑。

---

## 七、运行时数据布局

`/Users/tianwenliang/.agents/skills/ominicrawl/`（`config.yaml project_root` 配）：

```
project_crawl/
├── notes/
│   ├── bilibili/<UP主>/         *.md          # B站产出
│   ├── douyin/<博主>/            *.md          # 抖音产出
│   ├── xhs/<博主>/               *.md          # XHS 产出（剪藏单链接）
│   ├── wechat/                   *.md          # 微信产出
│   ├── boss/                     *.md          # 搜索结果
│   ├── jd/                       *.md
│   ├── linkedin/                 *.md
│   ├── tieba/<论坛>/             *.md
│   └── (clip 剪藏)              # 见 inbox
├── media/                                     # 缓存下载图/音
├── state/
│   ├── .watchlist_feishu_cache.md            # Watchlist TTL 缓存
│   ├── .subscription-crawl-cache.json        # 视频去重
│   └── clip_cache.json
├── logs/                                     # 跑批日志
├── credentials/feishu.json zhipu.json groq.json
└── inbox/                                     # (omitempty) 旧 inbox 队列
```

---

## 八、建议的清理与下一步（按改动风险排序）

### 8.1 立刻删除（0 引用 / 0 影响）
- `scripts/platforms/*` (5 个文件)，全部被 tools/* 替代。
- `scripts/publish_wiki.py` (28K)，pipeline 已用 push_to_feishu。
- `scripts/{link_crawl.py, fetch_url.sh, fetch_inbox_links.{sh,py}, backfill_*.py (5 个), cleanup_callout.py, dedup_xhs.py, delete_field.py, fix_timestamp.py, gen_detail_pages.py, migrate_legacy.py, verify_callout_fix.py, test_extract_fix.py, undo_detail_page.py, xhs_ocr_rapid.sh, summarize.py, batch_processor.py, monitor.sh, log_post_crawl.sh, lib.sh}`。
- 根目录 `bilibili/douyin/xiaohongshu/boss/linkedin/jd/tieba/` 各自 `crawl.py fetch.py search.py`，run_all.sh 是唯一引用 → **要么删 run_all.sh，要么把根目录脚本迁到 tools/**。

### 8.2 中等改动（保留兼容 / 重写文档）
- **合并 tools/* 与根目录 bilibili/douyin/.../fetch.py**：让根目录 fetch.py 只剩一个**兼容 shim**（转调 tools/），其它脚步迁 tools/。
- **合并 feishu.py 与 push_to_feishu.py**：把 feishu.py 变成 push_to_feishu.py 的薄壳。
- **common/llm.py** 退役，linked sink → common/summarize.py + 大注释说明：现在还调它的脚本。

### 8.3 架构优化
- **缓存迁移**：去重缓存应该统一在 `state/cache.json`（所有平台共享），而非每平台 split 文件。
- **总结去重**：同主题多条视频 → 取第一条总结插入博主 H1 下，避免重复。`bulll make push_aggregated 收一站毎场景 → 是该位置了**。
- **章节写flushed 重写：H1 = 博主。推送 时现在是按 push 顺序写，但同一博主都拼上不同 md，重复写H1 反而多 个 H1。建议在 push_aggregated 输入处接 “known_authors” set`，已写过 H1 的跳过。
- **vecron 实行**：`ominicrawl scripts/run_all.sh` 应是 *单文件* 总控 + `crawl.py watchlist` 不 再存在脚本入口。

### 8.4 文档同步
- **SKILL.md 重写**：重构 “平台契约/词典” 表上的 tools/crawl_imagec 还是 crawl_batch ?
- **scripts/README.md 重写** ：如果 8.1 都 采纳，scripts/ 只剩 README.md 本身。

---

