# Handoff Report — crawl/skills 0723 完整版

> 生成时间: 2026-07-23 19:30
> 接续对话: 上一个对话处理了大量 crawl/skills 架构重构和 bug 修复

---

## 1. 当前架构概览

### 1.1 目录结构

```
crawl/                           # 主工作目录（git repo: ~/.agents/skills/crawl）
├── SKILL.md                     # 主入口
├── config.yaml                 # 全局配置
├── common/                     # 公共模块
│   ├── paths.py                # 路径配置（代理到 ominicrawl-core）
│   ├── util.py                 # 工具函数（代理到 ominicrawl-core）
│   ├── opencli_bridge.py       # opencli 浏览器桥（代理到 ingest-wx）
│   └── state/                  # SQLite 去重缓存
├── common-asr/                 # 语音转写层
│   ├── SKILL.md
│   ├── transcribe.py           # mlx-whisper 主路
│   └── 模型列表.md
├── common-flow/                # 调度台
├── common-publish/             # 发布层
│   └── subscription_log.py     # 抓取台账
├── common-summary/             # 总结层
├── common-today/               # 每日汇总生成器
│   └── gen_today.py            # 生成 <date>-index.md
├── common-ocr/                 # OCR 层
├── ingest-bilibili/            # B站爬取
├── ingest-douyin/             # 抖音爬取
├── ingest-xhs/                # 小红书爬取
├── ingest-wx/                 # 微信/剪藏爬取
├── ingest-search/             # 搜索型平台
│   ├── linkedin.py            # 领英（已修复）
│   ├── jd.py                 # 京东
│   └── tieba.py              # 贴吧
└── logs/                      # 日志
```

### 1.2 关键路径配置

| 路径 | 值 |
|------|-----|
| VAULT | `/Users/tianwenliang/Documents/steven_vault` |
| subscription | `$VAULT/subscription/` |
| watchlist | `$VAULT/subscription/watchlist.md` |
| index | `$VAULT/subscription/<date>-index.md` |
| subscription_log | `$VAULT/subscription/subscription_log.md` |
| media | `$VAULT/media/` |

---

## 2. 平台文件落盘规范

### 2.1 三大平台（抖音/B站/小红书）

```
subscription/
├── douyin/
│   ├── 东方红老陈/
│   │   └── 2026-07-23_帖子标题.md
│   └── 口罩哥研报60秒/
│       └── 2026-07-23_帖子标题.md
├── bilibili/
│   ├── -LKs-/
│   │   └── 2026-07-23_帖子标题.md
│   └── ...
└── xiaohongshu/
    └── 博主名/
        └── 2026-07-23_帖子标题.md
```

**index 格式:**
- H1 = 平台名（抖音/B站/小红书）
- H2 = 博主名
- H3 = 帖子标题
- 正文 = `![[subscription/<plat>/<author>/<file>.md]]`

### 2.2 LinkedIn

```
subscription/linkedin/
├── AI销售/
│   └── 0723_<公司>_<职位>.md
├── AIBD/
│   └── ...
├── 销售总监/
│   └── ...
└── 其他/
    └── ...
```

**index 格式:**
- H1 = 领英
- H2 = 关键词（如 AI销售、AIBD、销售总监）
- H3 = 职位名

### 2.3 JD 购物

```
subscription/jd/
├── sony-xm6/
│   └── 0723_多平台比价.md
├── bose-qc45/
│   └── ...
└── 小米抗噪耳机/
    └── ...
```

**index 格式:**
- H1 = JD
- H2 = 关键词（产品名）
- H3 = 多平台比价

### 2.4 贴吧

```
subscription/tieba/
└── 少年西游记/
    └── 2026-07-23_帖子标题.md
```

**index 格式:**
- H1 = 贴吧
- H2 = 贴吧名
- H3 = 帖子主题

### 2.5 微信

剪藏入口 → Apple 备忘录 → 落盘到 `vault/00_inbox/`

---

## 3. 入口设计

### 3.1 爬取触发

| 命令 | 说明 |
|------|------|
| `爬取全部` | clip + watchlist（全流程） |
| `爬取剪藏` | clip（只跑剪藏链接） |
| `爬取平台` | watchlist（只跑平台爬取） |

### 3.2 watchlist.md 结构

```markdown
## 抖音 (douyin)
| 博主 | 平台主页 |
| ---- | -------- |
| 东方红老陈 | https://... |

## B站 (bilibili)
...

## 领英 (linkedin)
抓取方式: opencli linkedin search <关键词> --location <城市>

| 关键词 | 城市 |
| ---- | ---- |
| AIBD | 深圳 |
| AI销售 | 深圳 |
| 销售总监 | 深圳 |

## 抓取触发
```

---

## 4. 转录配置

### 4.1 当前 ASR 模型优先级

```
primary: mlx (本地 mlx-whisper)
bailian: paraformer-mtl-v1 (免费额度已耗尽，待恢复)
groq: 已禁用 (401 错误)
xfyun: 已禁用
```

### 4.2 config.yaml 转录配置

```yaml
transcription:
  primary: local
  fallback: local
  local:
    engine: mlx_whisper
    model: small
    device: ane
    note: mlx主路（bailian耗尽期间）
```

### 4.3 模型列表位置

`/Users/tianwenliang/.agents/skills/crawl/common-asr/模型列表.md`

---

## 5. 本次对话修复的 Bug

### 5.1 LinkedIn 爬取修复（已完成）

**问题:**
- `get_linkedin_keywords()` 从飞书读取（已弃用）
- 正则表达式无法匹配 URL 中包含 `)` 的链接
- 文件末尾 `for t in crawl_batch()` 类型错误

**修复:**
1. 添加 `get_linkedin_keywords_from_vault()` 从 vault watchlist.md 读取
2. 切换到 crawl 根目录运行（修复 import 路径）
3. 改用分步提取：简单正则 + `/jobs/view/` 过滤
4. 修复公司名称提取和标题过滤

**测试结果:**
- ✅ AIBD: 7 个职位
- ✅ AI销售: 2 个职位
- ✅ 销售总监: 7 个职位
- **总计: 16 个新职位**

### 5.2 每日 Index 生成

**问题:**
- LinkedIn 文件日期是 0628，未进入 0723-index
- gen_today.py 按 author 分组逻辑正确

**修复:**
- 将 LinkedIn 文件从 0628 重命名为 0723
- 重新生成 0723-index.md

---

## 6. 当前状态

### 6.1 0723-index.md 统计

| 平台 | H2 | 文件数 |
|------|-----|--------|
| 抖音 | 博主 | ~9 |
| B站 | 博主 | ~6 |
| 小红书 | 博主 | ~30 |
| 领英 | 关键词 | 33 |
| JD | 关键词 | 3 |
| 贴吧 | 贴吧名 | 16 |
| **总计** | | **73 篇** |

### 6.2 平台登录状态

| 平台 | 状态 | 备注 |
|------|------|------|
| bilibili | ✅ logged_in | |
| douyin | ✅ logged_in | |
| xiaohongshu | ✅ logged_in | |
| linkedin | ✅ logged_in | |
| JD | ✅ logged_in | |
| boss | ❌ disabled | 用户禁用 |

### 6.3 opencli session

| Session | 状态 | 说明 |
|---------|------|------|
| main | ✅ 正常 | 用户主 Chrome |
| dy2s6y2k | ✅ 正常 | 爬虫专用 Chrome |
| bzkxtgkb | ✅ 正常 | LinkedIn 专用 |

---

## 7. 待解决问题

### 7.1 已知问题

1. **bailian 转录额度耗尽**: `paraformer-mtl-v1` 免费额度已用完，需等待恢复或充值
2. **LinkedIn 详情抓取较慢**: 每次抓取 7-16 个职位详情需要较长时间
3. **小红书登录偶尔失效**: 需要检查 cookie 持久化机制

### 7.2 潜在优化

1. **转录并行化**: 当前串行处理，可考虑多 worker
2. **缓存机制优化**: 确保已抓取内容不重复爬取
3. **watchlist 更新**: 需要从 vault 动态读取，不硬编码

---

## 8. Git 提交历史

### 8.1 crawl 仓库

```
2b75755 fix: LinkedIn 爬取完全修复
e373fe3 fix: LinkedIn 爬取修复
ec31a80 refactor: watchlist和subscription_log移至subscription目录
ad068c9 fix: generate 函数按 author 分组，避免重复 H2
c0e274b fix: 清理 tieba 重复文件 + 重新生成 index
9ac548a fix: LinkedIn 目录清理 + 重新生成 index
21d6d06 fix: 修复 import 路径 + LinkedIn/JD 去重和目录结构
```

### 8.2 vault 仓库

```
4d3254e fix: LinkedIn 爬取完成，更新台账
ebb5484 fix: LinkedIn 文件日期改为 0723，重新生成 index
```

---

## 9. 关键代码位置

### 9.1 爬取脚本

| 平台 | 脚本 | 说明 |
|------|------|------|
| 抖音 | `ingest-douyin/` | |
| B站 | `ingest-bilibili/` | |
| 小红书 | `ingest-xhs/` | |
| 领英 | `ingest-search/linkedin.py` | 已修复 |
| JD | `ingest-search/jd.py` | |
| 贴吧 | `ingest-search/tieba.py` | |

### 9.2 发布脚本

| 功能 | 脚本 | 说明 |
|------|------|------|
| 发布 | `common-publish/publish_vault.py` | |
| 台账 | `common-publish/subscription_log.py` | |
| 每日汇总 | `common-today/gen_today.py` | |

### 9.3 转录

| 功能 | 脚本 | 说明 |
|------|------|------|
| mlx 转录 | `common-asr/transcribe.py` | 主路 |
| 模型列表 | `common-asr/模型列表.md` | 模型配置 |

---

## 10. 下一步工作建议

1. **测试全流程跑批**: 确认所有平台都能正常爬取
2. **优化转录性能**: 考虑启用 bailian 新模型或 Groq
3. **完善缓存机制**: 确保重复内容不重复爬取
4. **清理旧文件**: 删除 ominicrawl 目录，迁移到 crawl

---

## 11. 快速命令参考

```bash
# 爬取 LinkedIn
cd /Users/tianwenliang/.agents/skills/crawl/ingest-search
python3 linkedin.py 0723

# 生成每日 index
cd /Users/tianwenliang/.agents/skills/crawl/common-today
python3 gen_today.py 2026-07-23

# 检查 opencli 状态
opencli auth status | grep -E "linkedin|douyin|bilibili|xiaohongshu|jd"

# 检查 vault git 状态
cd /Users/tianwenliang/Documents/steven_vault
git status

# 检查 crawl git 状态
cd /Users/tianwenliang/.agents/skills/crawl
git status
```

---

