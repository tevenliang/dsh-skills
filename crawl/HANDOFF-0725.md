# HANDOFF — 2026-07-24 爬取 + 0725 代码改进

---

## 一、0724 爬取结果

**总耗时：57 分钟 | 退出码：0 | 7/7 平台全部完成**

| 平台 | 结果 |
|---|---|
| 抖音 | ✅ 18 博主 |
| B站 | ✅ 45 博主 |
| 小红书 | ✅ 11 博主 |
| 京东 | ✅ 3 关键词 |
| LinkedIn | ✅ 3 组关键词（39 职位）|
| 贴吧 | ✅ 1 吧（10 帖）|
| Boss直聘 | ⏭️ 工具未启用 |

### 关键数据

- **音频提取**：32 条，平均 58s，最长 236s
- **转录总计**：66 条（Groq 63 + Bailian 1 + MLX 2）
- **总结成功**：75 条（GLM → Bailian fallback），全部成功
- **去重跳过**：272 次
- **Supervisor 干预**：0 次

### 交付物

- `subscription/0724-index.md`：91 条，6 平台
- 各平台子目录 md 文件若干

---

## 二、0725 代码改进

### 1. common_supervisor 全套上线

路径：`~/.agents/skills/crawl/common_supervisor/`

**文件**：
- `supervisor.py` — 进程监控 + 卡死检测 + 自动恢复
- `_injection.py` — 5 个 recovery hook 注入（Groq/Bailian/MLX/GLM/Bailian-text）
- `patterns.py` — 异常模式库
- `recovery.py` — 恢复策略
- `state.py` — 状态持久化

**注入点**：`common-flow/crawl.py` 的 `_bootstrap()` 末尾调用 `install_recovery_hooks()`

**Supervisor 包装**：`run.sh` 默认走 supervisor，`--no-supervisor` 跳过调试

### 2. Bailian 文本/ASR 配额检查

路径：`~/.agents/skills/crawl/common_supervisor/check_bailian_quota.py`

**功能**：爬取前查所有 text + ASR 模型，写入 `state/bailian_quota.json` + 更新 `模型列表.md`

**Text 模型（9 个，2026-07-25 快照）**：

| 模型 | 剩余% | 状态 |
|---|---|---|
| `qwen3.5-plus` | 100% | ⭐ 推荐 |
| `qwen-plus-latest` | 100% | ✅ |
| `qwen3.5-flash` | 98.9% | ✅ |
| `qwen3.7-max` | 60.2% | ⚠️ |
| ... | | |

**ASR 模型（仅支持本地文件，6 个）**：

| 模型 | 剩余% | 状态 |
|---|---|---|
| `fun-asr-mtl` | 99.6% | ✅ 主力 |
| `fun-asr-2025-08-25` | 98.2% | ✅ |
| `fun-asr-mtl-2025-08-25` | 56.9% | ✅ |
| `fun-asr-2025-11-07` | 19.2% | ⚠️ 备用 |
| `paraformer-8k-v1` | 无免费额度 | ❌ |
| `paraformer-mtl-v1` | 无免费额度 | ❌ |

**阈值**：剩余 <10% 视为不可用，自动跳过

### 3. ASR 转录链路（已更新）

```
Groq Whisper API（RTF≈0.1）
    ↓
Bailian ASR → _load_asr_quota_cache() 读缓存
             → _LOCAL_FILE_SUPPORTED = {fun-asr-mtl*, paraformer-8k-v1, fun-asr-2025-08-25, fun-asr-2025-11-07}
             → 选剩余最多的可用模型
    ↓
MLX Whisper（Mac ANE，无限额度）
```

**注入**：`transcribe.py` 加载时读 `state/bailian_quota.json`，不用每次调 CLI

### 4. Summarize 总结链路（已更新）

```
GLM-4-flash（SSL EOF 风险）
    ↓ 外层 for 循环自动切
Bailian Text → _get_cached_best_model() 读缓存 → qwen3.5-plus（100%）
    ↓
MiniMax-M2.7（无限，第三兜底）
```

**注意**：`call_glm` 不加重试逻辑，外层 `for eng in ["glm","bailian","minimax"]` 自动 fallback

### 5. common-today 日期格式修复

**问题**：`crawl.py` 调用 `gen_today.py` 不传日期，`gen_today.py` 期望 `YYYY-MM-DD`，`crawl.py` 用 `YYMMDD`

**修复**：`crawl.py` line 543 传入 `f"20{date[:2]}-{date[2:4]}-{date[4:6]}"`

### 6. LinkedIn 去重（未完成）

**问题**：LinkedIn 搜索结果同一职位出现 3-4 次重复

**TODO**：在 `ingest-search` 或 `common-publish` 层加标题+链接去重

---

## 三、踩坑记录

### 0724

| 问题 | 根因 | 处理 |
|---|---|---|
| GLM SSL EOF 频繁 | VPN 路由不稳定 | `summarize_text` 外层 for 循环已自动切 Bailian，75/75 成功 |
| Chrome 扩展断连 | yizhini profile daemon 断连 | 修复命令：`"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --profile-directory="Profile 1"` |
| Groq 误以为禁用 | 7-18 临时禁用后未更新记忆 | Groq 已恢复（RTF≈0.1），是 ASR 最快路径 |

### 0725

| 问题 | 根因 | 处理 |
|---|---|---|
| Bailian text 模型需查配额 | `qwen3.7-max` 仅剩 60% | 爬取前 `check_bailian_quota.py` 查，写入缓存 |
| Bailian ASR 只支持部分模型 | `fun-asr-flash*` 等不支持本地文件 | `_LOCAL_FILE_SUPPORTED` 白名单过滤 |
| `_check_bailian_quota` 放错位置 | 每次 summarize 调用都调 CLI | 爬取前查一次，summarize_text 读 JSON |
| `gen_today.py` 日期格式错 | YYMMDD vs YYYY-MM-DD | crawl.py 传参时转换 |

---

## 四、Chrome Profile 映射（2026-07-24 实测）

| Chrome 目录 | 账号 | opencli ID | 用途 |
|---|---|---|---|
| Profile 1 | yizhini@gmail.com | dy2s6y2k | 爬虫专用 ✅ |
| Default (bzkxtgkb) | teven.liang@gmail.com | bzkxtgkb | 主账号，禁止操作 |

**断连修复**：
```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --profile-directory="Profile 1"
# 等 5-8 秒后 opencli profile list 验证
```

---

## 五、运行命令

```bash
# 标准跑批（Supervisor 监护）
cd ~/.agents/skills/crawl && ./run.sh watchlist

# 调试（跳过 Supervisor）
cd ~/.agents/skills/crawl && ./run.sh watchlist --no-supervisor

# 环境状态
cd ~/.agents/skills/crawl && ./run.sh status

# 手动查 Bailian 配额
~/.agents/skills/crawl/.venv/bin/python3 common_supervisor/check_bailian_quota.py
```

---

## 六、下次跑批前检查清单

- [ ] opencli Chrome dy2s6y2k 是否 connected
- [ ] `bailian_quota.json` 是否在 24h 内更新
- [ ] LinkedIn 去重（TODO）
