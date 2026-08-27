---
name: crawl-vm
metadata:
  version: 1.0.0
description: >
  crawl-vm 是完全运行在 VM (175.178.210.156) 上的爬取套件。
  支持抖音、B站双平台，抓取视频→下载音频→Groq转录→发布到vault。
  **所有代码在 VM 上，DSH Mac端仅作为触发和监控。**
disable-model-invocation: true
---

# crawl-vm — VM 爬取套件

## 架构

```
DSH (Mac)              VM (175.178.210.156)
   │                          │
   │  ./run.sh               │
   ├────────────────────────►  │
   │                   ~/.dsh/skills/crawl-vm/
   │                   ├── run.sh              # 入口脚本
   │                   ├── config.yaml         # 配置
   │                   ├── pipeline/run.py     # 主流程
   │                   ├── platforms/         # 爬虫
   │                   │   ├── douyin/crawler.py
   │                   │   └── bilibili/crawler.py
   │                   └── common/            # 公共模块
   │                       ├── transcribe.py  # Groq转录
   │                       ├── summarize.py   # Bailian总结(可选)
   │                       └── publish_vault.py
   │
   │                      vault: /home/ubuntu/webdav/steven_vault
   │                      笔记: vault/notes/{platform}/
   │                      聚合: vault/subscription/{platform}-hot.md
   │
   ◄─────────────────────── 完成
```

## 触发词

| 你说 | 程序调 | 说明 |
|------|--------|------|
| 「爬取抖音」/「爬取douyin」 | `./run.sh douyin` | 爬取抖音watchlist |
| 「爬取B站」/「爬取bilibili」 | `./run.sh bilibili` | 爬取B站watchlist |
| 「爬取全部」 | `./run.sh all` | 爬取所有平台 |
| 「爬取单条douyin」+ ID | `./run.sh douyin --douyin-ids <id>` | 爬取指定视频 |

## 快速运行

```bash
# SSH到VM，进入crawl-vm目录
ssh ubuntu@175.178.210.156
cd ~/.dsh/skills/crawl-vm

# 激活虚拟环境
. ~/.agents/skills/crawl/.venv/bin/activate

# 运行
./run.sh all
# 或指定平台
./run.sh douyin
./run.sh bilibili
```

## Watchlist 格式

`vault/watchlist.md` 支持两种格式：

### 新格式（推荐）
```markdown
## 抖音 (douyin)

| 平台 | 博主 | ID | 备注 |
|------|------|-----|------|
| bilibili | 闻哥 | 3546977052658531 | |

## Douyin

| 博主 | 分类 | url |
|------|------|-----|
| 黄士铨看世界 | 财经 | https://www.douyin.com/user/MS4wLjABAAAA... |
```

### 旧格式（兼容）
```markdown
## 抖音 (douyin)
| 博主 | 分类 | url |
| ... |
```

## Credential

```
~/.agents/credentials/ominicrawl/
├── groq.json              Groq API key（转录用）
├── bilibili.txt           B站cookie（SESSDATA）
└── douyin.json            抖音cookie（备用）

~/.bailian/config.json     Bailian API（总结用，可选）
```

## 核心流程

```
1. 解析 watchlist.md
   └── 提取博主 sec_user_id (Douyin) 或 mid (Bilibili)

2. 获取视频列表
   └── Douyin: fetch_user_post_videos (需要 a_bogus 签名)
   └── Bilibili: fetch_user_videos (需要 WBI 签名)

3. 去重检查
   └── 对比 state/run_*.events.jsonl，已处理的跳过

4. 下载音频
   └── Douyin: MP3
   └── Bilibili: M4A
   └── 重试机制: 最多3次

5. 转录 (Groq)
   └── MP3/M4A → WAV → Groq Whisper
   └── VPN代理: http://127.0.0.1:7890

6. 总结 (Bailian, 可选)
   └── GLM-4-Flash 生成摘要

7. 发布到 vault
   └── 笔记: vault/notes/{platform}/{date}-{title}.md
   └── 聚合: vault/subscription/{platform}-hot.md
```

## 关键文件

| 文件 | 说明 |
|------|------|
| `config.yaml` | 配置文件（vault路径、API配置） |
| `run.sh` | 入口脚本 |
| `pipeline/run.py` | 主流程 |
| `platforms/douyin/crawler.py` | 抖音爬虫（a_bogus签名） |
| `platforms/bilibili/crawler.py` | B站爬虫（WBI签名） |
| `common/transcribe.py` | 转录服务 |
| `common/summarize.py` | 总结服务 |
| `common/publish_vault.py` | 发布到vault |
| `common/watchlist.py` | 解析watchlist |

## 状态日志

```
~/.dsh/skills/crawl-vm/state/run_YYYYMMDD_HHMMSS.events.jsonl
```

## 已知问题

- **Bailian总结**: Token过期时总结会失败，但不影响转录
- **Bilibili用户**: 私密用户可能返回0视频
- **下载超时**: 某些视频URL较慢，有重试机制

## 监控

```bash
# 查看vault输出
ls /home/ubuntu/webdav/steven_vault/notes/douyin/
ls /home/ubuntu/webdav/steven_vault/notes/bilibili/

# 查看聚合
cat /home/ubuntu/webdav/steven_vault/subscription/douyin-hot.md
cat /home/ubuntu/webdav/steven_vault/subscription/bilibili-hot.md
```
