# ominicrawl

> 统一多平台内容抓取流水线 — 链接剪藏 + 博主监控 + 关键词搜索
> **Skill 根**: `~/.agents/skills/ominicrawl/`
> **唯一真相源**: `SKILL.md`（agent 记忆）+ `config.yaml`（配置）

---

## 快速状态（2026-07-17）

| 平台 | 状态 | 方案 |
|------|------|------|
| 小红书 | ✅ | xhs-cli 列表 + xhs-downloader clip |
| 抖音 | ✅ | 抖音 Web API（`lib/douyin_api` + Cookie 鉴权，**不走 opencli/Chrome**） |
| B站 | ✅ | opencli browser |
| 领英 | ✅ | opencli site adapter + browser detail |
| Boss | ✅ | opencli site adapter |
| 京东 | ✅ | opencli site adapter |
| 贴吧 | ✅ | aiotieba HTTP API |
| 微信 | ✅ | wechat-fetcher |
| 通用链接 | ✅ | trafilatura |

**已知 bug**: 全清（2026-07-17）

---

## 入口命令

```bash
SKILL=/Users/tianwenliang/.agents/skills/ominicrawl
PY=$SKILL/.venv/bin/python3   # 技能内 venv（双软件共享，详见下方「Python 环境」）

$PY $SKILL/crawl.py watchlist           # 全平台 watchlist（凌晨 06:00 自动跑）
$PY $SKILL/crawl.py clip                # 剪藏队列
$PY $SKILL/crawl.py url "<URL>"         # 单条剪藏
$PY $SKILL/crawl.py watchlist --platform tieba   # 只跑指定平台
```

---

## Python 环境（.venv，2026-07-18 迁移后）

- **依赖装在技能内 `.venv`**：`~/.agents/skills/ominicrawl/.venv`（基于 managed Python 3.13.12 创建）。
- **双软件共享**：codex / WorkBuddy 经统一根软链访问同一份 `.venv`，一份依赖两端通用，不装进各自 runtime 的 site-packages。
- **自动启用**：`run.sh` 优先检测 `$SKILL/.venv/bin/python3`，存在即用；手动跑 `crawl.py` 也用 `$PY` 指向它。
- **重建命令**：若 `.venv` 丢失——
  ```bash
  ~/.workbuddy/binaries/python/versions/3.13.12/bin/python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt   # 含 httpx==0.27.2 钉版 + importlib_resources
  ```
- **不提交**：`.venv/` 已加入 `.gitignore`，不随 git 提交；`requirements.txt` 入仓（可复现，89 行锁定版）。
- ⚠️ `execjs` 在 PyPI 上的包名是 **`PyExecJS`**，安装时别写错（曾因此整批安装中止）。
- ⚠️ `httpx` 必须钉 **`==0.27.2`**：`lib/douyin_api` 在导入时调用 `httpx.Client(proxies=...)`，而 httpx≥0.28 已移除 `proxies=` 参数会直接 `TypeError`。
- ⚠️ `lib/douyin_api` 子库额外需要 **`importlib_resources`**（标准库 `importlib.resources` 的 backport），不在主依赖列表，漏装会 `ModuleNotFoundError`。

---

## 落点（两条独立通道 — 2026-07-21 严格分线）

### 剪藏 (clip — 唯一入口/出口)
- 入口: `macOS 备忘录「网页剪藏」` + `crawl url <URL>`
- 出口 md: `$VAULT/00_inbox/MMDD-<title>.md`
- 出口图片: `$VAULT/media/<md5>.<ext>`

### 监控 (watchlist)
- 入口: `$VAULT/watchlist.md`
- 出口: `$VAULT/subscription/<平台>/hot.md` (当前自然月) + `<YYYYMM><平台>.md` (按月归档)
- 图片: `$VAULT/media/<md5>.<ext>`

双平台 $VAULT 回退：$VAULT 环境变量 → mac=~/Documents/steven_vault，VM=/home/ubuntu/webdav/steven_vault。

---

## 关键踩坑结论（必读）

1. **Python 环境**: 依赖装在技能内 `.venv`（见「Python 环境」节）。`run.sh` 自动优先用 `.venv/bin/python3`；手动跑也请用它，不要依赖系统 python3 或各软件 managed python
2. **Chrome profile**: 主 Chrome（teven.liang）绝对不能动；yizhini 副 profile 爬完即关
3. **opencli**: site adapter 不依赖 extension 即可工作；extension 只影响 browser bridge
4. **转录**: bailian(paraformer-8k-v2, primary) → mlx-whisper（本地 fallback）。groq 2026-07-18 起永久禁用（key 401）。详 v11 §6.10。
5. **贴吧**: 完全不走 opencli，用 aiotieba HTTP API，最稳
6. **网络代理陷阱（2026-07-18 已修; 2026-07-20 注解）**: 本机 Clash Verge 经 launchd 全局注入 `HTTPS_PROXY=127.0.0.1:7897`。bailian/dashscope 是阿里云国内端点，走代理会被路由海外导致超时/失败。`common/transcribe.py` 的 `_bailian_run` 已自动剥离 bailian 子进程的代理变量。**2026-07-20 更新**：groq 主链路已废（2026-07-18 起 `_GROQ_DISABLED=True`），所以"不要在 run.sh 全局 unset 代理否则会挂 groq"的警告**已过期**——但仍**不建议**全局 unset，因为抖音视频下载走 urllib + HTTPS_PROXY，且 baoxian 等 CDN 也需代理。抖音 `lib/douyin_api` 用自己 config.yaml proxy，**必须**设 `proxies: {http: "http://127.0.0.1:7897", https: "http://127.0.0.1:7897"}`（dict 格式，utils.py 不认字符串），否则直连被抖音反爬 TCP 重置。

---

## 文档索引

| 文件 | 用途 |
|------|------|
| `SKILL.md` | agent 记忆入口（触发词/铁律/踩坑） |
| `STRUCTURE.md` | 程序架构详解 |
| `files/04-known-bugs-and-todos.md` | bug 追踪（当前全清） |
| `files/03-chrome-profile-gotchas.md` | Chrome profile 安全铁律 |
| `files/05-recovery-procedures.md` | 故障排查 SOP |
| `files/06-platform-status.md` | 平台当前状态 |
