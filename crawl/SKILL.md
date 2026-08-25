---
name: crawl
metadata:
  version: 3.1.1
description: >
  crawl 多平台内容抓取套件。说「爬取」即调 run.sh 全流程（watchlist → clip → report）。 **唯一入口**，不拆多个
  SKILL。
disable-model-invocation: true
---

# crawl — 唯一入口

## 触发词

| 你说 | 程序调 | 说明 |
|------|--------|------|
| 「爬取全部」 | `run.sh all` | watchlist → clip → report，全流程 |
| 「爬取B站」/「爬取抖音」/「爬取小红书」… | `run.sh watchlist --platform <平台>` | 只跑指定平台 watchlist |
| 「爬取收件箱」 | `run.sh clip` | 只 clip，不 watchlist |

**平台名映射**：`bilibili` / `douyin` / `xiaohongshu` / `wx` / `tieba` / `jd`

## Credential（统一路径，2026-07-23 固化）

```
~/.agents/credentials/ominicrawl/
├── bilibili.txt      B站 SESSDATA cookie
├── xiaohongshu.txt   小红书登录态
├── douyin.json       抖音（备用）
├── groq.json         Groq API key（**ASR 唯一主路, 2026-07-30 极简模式修 #12**）
└── zhipu.json        智谱 API key（备用）
```

## 跑批前检查

```bash
cd ~/.agents/skills/crawl
./.venv/bin/python3 health_check.py
```

必须全部 ✅ 才能跑批。任何 ❌ 先修复。

**ASR 极简模式（2026-07-30 修 #12）**：transcribe() 只走 Groq. Bailian/MLX/Tencent 函数保留但默认不调用, 无需刷新它们的凭证. Groq 失败 → raise RuntimeError → caller catch + `[ASR.FATAL]` 跳过该条.

## crawl 3.1.1 — B站/抖音 转录改走 VM（2026-08-11）

Groq 对中国大陆 IP 永久 403（与 VPN 无关），B站/抖音转录长期失效。3.1.0 把「转录→总结→发布」整体迁移到 VM（`175.178.210.156`，Whisper base(标点prompt) + Zhipu GLM 生成型总结），Mac 端只保留「下载」。

- **开关**：`config.yaml` 的 `vm.asr_routing`（默认 `true`）。开启后 `ingest-bilibili`/`ingest-douyin` 下载完音频即调 `tools/handoff_vm.handoff_to_vm()` 上传 VM `inbox/`，返回 `md=None` 让 `pipeline/run.py` 跳过本地转录与总结（无需改 pipeline）。
- **VM 端**：`systemd` 服务 `crawl-transcribe` 常驻，30s 轮询 `inbox/`，串行跑 `transcribe_worker.py`（FunASR 转录 → Zhipu 总结 → `publish_vault.append_single_to_hot` 写 vault），成功删源音频、meta 归档 `done/`、刷新 `04_agent/report/crawl_op_vm_YYYYMMDD.md`。
- **契约**：`inbox/<platform>_<video_id>.wav` + 同名 `.meta.json`（`{platform,author,title,source_url,publish_date}`）。
- **积压回填**：`~/Documents/agent_spaces/ominicrawl/backfill_pending_vm.py` 把 `state/pending_audio/bilibili/*.wav` 补元数据后批量上传 VM。
- **监控**：`ssh ubuntu@175.178.210.156 'journalctl -u crawl-transcribe -f'`；看 vault `04_agent/report/crawl_op_vm_*.md`。
- **设计/进度**：`ominicrawl/crawl-3.1.0-design.md` · `ominicrawl/crawl-3.1.0-progress.md`。

## crawl 3.1.1 — 小红书 OCR 改走 VM（2026-08-14）

watchlist 小红书博主第4列为 `OCR=Y` 的笔记，由 VM OCR daemon 异步完成图片文字识别 → 覆盖写回 vault。

- **触发**：Mac `ingest-xhs` 在 `append_single_to_hot()` 后，判断 watchlist 第4列=OCR=Y → 调 `tools/handoff_vm_ocr.handoff_xhs_ocr_to_vm()` rsync 到 VM `ocr_inbox/`
- **VM 端**：`systemd` 服务 `ocr-daemon` 常驻，30s 轮询 `~/crawl-transcribe/ocr_inbox/`，串行跑 tesseract（chi_sim+eng）OCR → 替换 md 中 wikilinks 为 OCR 文字 → `publish_vault.append_single_to_hot()` 覆盖写 vault → 清理源目录
- **幂等**：publish_vault 已按 source_url 维去重，同一 note_id 多次 publish 只保留最新结果
- **回执**：VM 写 `vault/04_agent/report/crawl_op_ocr_YYYYMMDD.md`
- **监控**：`ssh ubuntu@175.178.210.156 'journalctl -u ocr-daemon -f'`

## 程序架构（v2 / 2026-07-30）

```
Codex/shell                    ← 你手动 ./run.sh all
└─ run.sh                      ← 唯一入口（shell）
   └─ supervisor.py            ← 唯一父进程（普通进程，不依赖 launchd）
      ├─ preflight             bailian console auth + model smoke test
      ├─ watchlist 阶段
      │    └─ spawn: ingest-{platform}/crawl.py  (sub-process)
      │         └─ item loop: [download → ASR → summary]  每步有 deadline
      ├─ clip 阶段 (同结构)
      └─ report 阶段
           └─ 读 state/run_<tag>.events.jsonl → 写 OP md
```

**唯一入口**：`./run.sh all`（手触发，无 plist/daemon）

**ActionMonitor**（取代 StallMonitor）：
- 每 30s 检查子进程 active item 是否变化
- 10min (600s) 无变化 → 杀子进程 + append_event sub_process_killed
- 不再等 30min 沉默，不发 macOS 通知，不写 faulthandler dump

**with_deadline 包装器**（`common/with_deadline.py`）：
- 子进程内每阶段 download=90s / ASR=180s / summary=60s / OCR=30s
- 超时: 函数 daemon thread 随进程退出回收, item 标 deferred 继续下一个
- 用户拍板 Q-α: ASR = 180s

**state 文件**（按 run_tag 拆分）：
- `state/run_<YYYYMMDD>_<HHMMSS>_<PID>.events.jsonl` — append-only 事件流
- `state/run_<tag>.status.json` — 状态快照
- `state/run_<tag>.recovery.json` — provider cooldown
- `logs/run_<tag>.out` — 人类可读 stdout

**❌ 不再做的事**：
- 不再 plist (LaunchAgent 已 trash 2026-07-30)
- 不再 macOS Notification Center 弹窗
- 不再 faulthandler dump
- 不再 StallMonitor 沉默判定
- 不再 parse stdout 反猜 OP 数据 (events.jsonl 是唯一真实源)

common_supervisor/
├── supervisor.py               全流程调度台（唯一主程序）
├── run_meta.py                 run_tag + events.jsonl + status/recovery
├── action_monitor (内嵌)       per-item watchdog (10min grace)
├── _eagain_retry.py           macOS fork EAGAIN 重试
├── check_bailian_quota.py     bailian ASR 额度 smoke test
├── recovery.py                429/401/500 错误自动恢复
├── patterns.py                异常模式匹配
├── _injection.py              子进程内 provider 状态注入
└── state.py                   (兼容旧路径, 仍可用)

common/
├── with_deadline.py           (NEW) 通用 deadline 包装器
├── progress_tracker.py        进度行打印 (ActionMonitor 复用)
├── transcribe.py              → 实际是 common-asr/transcribe.py 的 re-export
├── clipboard.py
├── feishu_watchlist.py
├── opencli_bridge.py
├── paths.py
├── publish_vault.py
├── registry.py
├── summarize.py
├── summarize_markdown.py
├── util.py
└── window.py

common-asr/
└── transcribe.py              ASR 调用链: **Groq only** (2026-07-30 极简模式, 修 #12)
                               Bailian/MLX/Tencent 函数定义保留, 但 transcribe() 入口不再调用, 失败 raise RuntimeError

**❌ 不要拆多个入口 .py**：`run.sh` 是唯一入口，Python 层不暴露 CLI 入口。

## ASR 模型优先级（2026-07-30 修 #12: 极简模式）

```
Groq Whisper（whisper-large-v3, 480min/天免费, **唯一主路**）
    ↓ 失败 → raise RuntimeError（caller try/except 跳过该视频）
    ✗ Bailian / MLX / Tencent 全部 disable（不静默 fallback）
```

**极简模式动机（用户 2026-07-30 决定）**：
- Bailian / Tencent 免费额度太少（10h/月 → 一两天就没了）
- MLX 占 Mac 本地资源
- 用户目标：把 Groq ASR 做到完美, 单一故障域
- Fail-fast 哲学：Groq 挂了就立刻可见, 别让 bailian 静默撑 2 天悄悄烧额度
- 失败处理：transcribe() raise RuntimeError, caller（bilibili.py / douyin.py 等 4 处）已加 try/except 打 `[ASR.FATAL]` + 跳过该条, 不影响 batch 其它视频

> 注: `transcribe_bailian()` / `transcribe_mlx()` / `transcribe_tencent_asr()` 函数定义均保留（供将来手动 env 切回或 unit test 用），但 `transcribe()` 主入口不再调用.

### Groq（primary, **唯一**主路, 修 #10 #11 #12）
- 凭证：`~/.agents/credentials/ominicrawl/groq.json` (api_key)
- 免费额度：**480 分钟/天**（≈ 28 GB/天，无信用卡）
- 模型：`whisper-large-v3`（带 `prompt` 参数自动加中文标点）
- 单次 timeout：**200s**（= curl `--max-time 180` + 20s buffer，修复 150s 误杀长视频）
- 两阶段 cooldown（修 #11）：
  - 1×429 → cooldown 120s
  - 2×429 (cooldown 内再来) → cooldown 300s + 标记本批不再回 Groq
- 失败行为（修 #12, 2026-07-30）：`transcribe()` 直接 raise RuntimeError, 不再 fallback 到 bailian/mlx/tencent
- 注意：Groq 配额 480 min/天 是**总用量**，不是单条请求数

### Bailian / MLX-whisper / Tencent ASR（全部 disabled, 修 #12）

- **Bailian**：函数 `transcribe_bailian()` 保留, free-tier 10h/月太少 (用户原话: 「免得像腾讯云asr这样, 折腾半天, 原来才一个月10小时都不够」)
- **MLX-whisper**：函数 `transcribe_mlx()` 保留, 占 Mac 本地资源 (用户原话: 「不想耗费我本的mac资源」)
- **Tencent ASR**：函数 `transcribe_tencent_asr()` 保留, 同 bailian 额度理由

将来若 Groq 出大问题需要临时切换, 可手动注入某个 provider (例如 env `FORCE_TENCENT=1` 切到 Tencent) — 但默认极简模式不调用任何非 Groq 链路.

Bailian pool（按剩余量）：
1. `fun-asr-mtl-2025-08-25` 剩余 54%
2. `fun-asr-mtl` 剩余 40%
3. `fun-asr-2025-11-07` 剩余 19%

smoke test 状态见 `~/.agents/skills/crawl/模型列表.md`

## 已知限制

| 问题 | 解法 |
|------|------|
| B站 -412 | 等几分钟自动解封，或刷新 cookie |
| opencli Chrome 断开 | Chrome 中点一次 OpenCLI 扩展图标，等 5 秒 |
| 小红书 fork 失败 | 已加 EAGAIN retry，已修复 |
| Bailian Console token 过期 | `bl auth login --console` 刷新 |
