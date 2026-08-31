---
name: crawl-vm
metadata:
  version: 1.1.0
description: >
  crawl-vm 是完全运行在 VM (175.178.210.156) 上的爬取套件。
  支持抖音、B站、小红书三平台，抓取视频/图文 → 转录/总结 → 发布到 vault。
  **所有代码在 VM 上，DSH Mac端仅作为触发和监控。**
disable-model-invocation: true
---

# crawl-vm — VM 爬取套件

## 架构

```
DSH (Mac)                VM (175.178.210.156)
   │                              │
   │  ./run.sh <plat>           │
   │─────────────────────────►  │
   │                     ~/.dsh/skills/crawl-vm/
   │                     ├── run.sh              # 入口脚本 (走 supervisor)
   │                     ├── config.yaml         # 配置
   │                     ├── pipeline/run.py     # 主流程 (双平台+小红书)
   │                     ├── platforms/         # 爬虫
   │                     │   ├── douyin/crawler.py     (a_bogus 签名)
   │                     │   ├── bilibili/crawler.py   (WBI 签名)
   │                     │   └── xiaohongshu/crawler.py (xhshow + curl_cffi)
   │                     ├── common/            # 公共模块
   │                     │   ├── transcribe.py   (Groq Whisper)
   │                     │   ├── summarize.py    (Groq LLM)
   │                     │   ├── publish_vault.py
   │                     │   └── watchlist.py
   │                     └── common_supervisor/ # 守护
   │                         ├── supervisor.py  (ActionMonitor, 卡死自动 kill)
   │                         ├── run_meta.py     (run_tag + events.jsonl)
   │                         ├── state.py       (recovery.json / status.json)
   │                         ├── recovery.py    (provider cooldown / 切换)
   │                         └── patterns.py
   │
   │                  vault: /home/ubuntu/webdav/steven_vault
   │                  笔记: vault/subscription/{platform}/<author>/<YYYY-MM-DD>_<title>.md
   │                  聚合: vault/subscription/{platform}-hot.md
   │                  index: vault/subscription/<MMDD>-index.md
   │
   ◄──────────────────── 完成
```

## 触发词

| 你说 | 程序调 | 说明 |
|------|--------|------|
| 「爬取抖音」/「爬取douyin」 | `./run.sh douyin` | 爬取抖音 watchlist |
| 「爬取B站」/「爬取bilibili」 | `./run.sh bilibili` | 爬取 B站 watchlist |
| 「爬取小红书」/「爬取xhs」 | `./run.sh xiaohongshu` | 爬取小红书 watchlist |
| 「爬取全部」 | `./run.sh all` | 爬取所有平台 |
| 「爬取单条<平台>」+ ID | `./run.sh <plat> --<plat>-ids <id>` | 爬取指定视频/笔记 |

## 快速运行

```bash
# SSH 到 VM，进入 crawl-vm 目录
ssh ubuntu@175.178.210.156
cd ~/.dsh/skills/crawl-vm

# 走 supervisor 守护, 自动卡死检测
./run.sh all
# 或指定平台
./run.sh douyin
./run.sh bilibili
./run.sh xiaohongshu
```

## Watchlist 格式

`vault/subscription/watchlist.md` 支持以下段落:

```markdown
## 抖音 (douyin)
| 博主 | 分类 | url |
| 黄士铨看世界 | 财经 | https://www.douyin.com/user/MS4wLjABAAAA... |

## B 站 (bilibili)
| 博主 | 分类 | url |
| 林亦LYi | 财经 | https://space.bilibili.com/4401694 |

## 小红书 (xiaohongshu)
| 博主 | 分类 | url |
| 阿基米 | 财经 | https://www.xiaohongshu.com/user/profile/5866293c82ec3912a575bb88 |
```

## Credential

```
~/.agents/credentials/ominicrawl/
├── groq.json              Groq API key (转录用)
├── bilibili.txt           B站 cookie (SESSDATA)
├── xiaohongshu.txt        小红书 cookie (a1 + web_session + webId)
└── (douyin 从 ~/.dsh/skills/crawl/ingest-douyin/douyin_api/crawlers/douyin/web/config.yaml 读)
```

## 核心流程

```
1. 解析 watchlist.md
   └── 提取博主 ID (Douyin sec_uid / B站 mid / 小红书 user_id)

2. 获取笔记/视频列表
   └── Douyin: a_bogus 签名 + /aweme/v1/web/aweme/post/
   └── Bilibili: WBI 签名 + /x/space/wbi/arc/search
   └── Xiaohongshu: xhshow X-s 签名 + /api/sns/web/v1/user_posted

3. 去重检查 (is_processed)
   ├── vault 已有文件内容扫描 (跨子目录, 跨日期)
   └── frontmatter video_id / uid / source_url 匹配

4. 下载媒体
   ├── Douyin/Bilibili: curl 下载 MP3/M4A → ffmpeg 转 WAV
   └── Xiaohongshu: 图文帖直接 curl 下载图片到 media/xhs/

5. 转录 (Groq Whisper)
   └── MP3/M4A → WAV (16kHz mono) → Groq whisper-large-v3

6. 总结 (Groq LLM)
   └── 转录文本 (>300 字符) → Groq qwen/qwen3.8-27b
   └── 小红书纯文字帖直接用 desc 当 transcript

7. 发布到 vault
   ├── Douyin/Bilibili: subscription/<platform>/<MMDD>-<title>.md
   └── Xiaohongshu: subscription/xiaohongshu/<author>/<YYYY-MM-DD>_<title>.md
        + 图片下载到 media/xhs/<YYYY-MM-DD>_<HH.MM.SS>_<author>_<title>_<n>.{png,webp}

8. 生成 index
   └── subscription/<MMDD>-index.md (按平台+作者聚合, 含今天的笔记)
```

## 关键文件

| 文件 | 说明 |
|------|------|
| `run.sh` | 入口脚本 (走 supervisor) |
| `config.yaml` | 配置文件 (vault路径 / 平台启用 / 转录 / 总结) |
| `pipeline/run.py` | 主流程 (跟 run.py 同步) |
| `platforms/douyin/crawler.py` | 抖音爬虫 (a_bogus 签名) |
| `platforms/bilibili/crawler.py` | B站爬虫 (WBI 签名) |
| `platforms/xiaohongshu/crawler.py` | 小红书爬虫 (xhshow + curl_cffi) |
| `common/transcribe.py` | Groq Whisper 转录服务 |
| `common/summarize.py` | Groq LLM 总结服务 |
| `common/publish_vault.py` | 发布到 vault (通用 publish + xiaohongshu publish_xhs_note) |
| `common/watchlist.py` | watchlist 解析 (支持 douyin/bilibili/xiaohongshu 三平台) |
| `common_supervisor/supervisor.py` | 守护主程序 (ActionMonitor 卡死检测) |
| `common_supervisor/run_meta.py` | run_tag 生成 + events.jsonl |
| `common_supervisor/state.py` | status.json / recovery.json 状态管理 |
| `common_supervisor/recovery.py` | provider cooldown + 切换 |

## 状态日志

```
~/.dsh/skills/crawl-vm/state/
├── run_<YYYYMMDD>_<HHMMSS>_<PID>.events.jsonl  每条一次跑批的事件流
├── run_<YYYYMMDD>_<HHMMSS>_<PID>.status.json   当前快照
├── recovery.json                                provider cooldown 状态
└── supervisor.json                              supervisor 主状态 (run_tag, pid, etc)
```

## Supervisor 守护

`run.sh` 自动走 `common_supervisor.supervisor`:
- **ActionMonitor**: per-action 进度监控, 30min 卡死自动 kill (grace_sec=1800)
- **断流检测**: 30s select 超时, stdout 关闭时检查子进程退出
- **provider 切换**: recovery.py 自动 cooldown / 切换 (groq/bailian/mlx/glm_summary)
- **状态轮询**: `state/supervisor.json` 持续更新, 外部可轮询
- **stdout 实时解析**: PROGRESS_RE / PROGRESS_SUMMARY_RE 提取 phase + 进度

## Vault 文件名铁律

- ext4 单文件名 ≤ 255 字节 (UTF-8 汉字 3B)
- `common/util.py sanitize_filename(max_bytes=N)` 字节截断, UTF-8 边界安全
- `common/publish_vault.py safe_id(max_bytes=30) + safe_title(max_bytes=150)`, 完整文件名上限 ~179 字节
- 文件名长度违规时, wsgidav 返回 500, Remotely Save 整轮卡死

## 已知问题

- **抖音**: 需要 a_bogus 签名 (Python 依赖 `abogus` 模块)
- **小红书**: web_session cookie 60 天有效, 过期后需重新从 Mac Chrome 导出
- **Bailian 总结**: GLM API key 若过期, 总结会失败但不影响转录
- **下载超时**: 某些视频URL较慢, 有重试机制 (max_retries=3)

## 监控

```bash
# 查看 vault 输出
ls /home/ubuntu/webdav/steven_vault/subscription/{douyin,bilibili,xiaohongshu}/
ls /home/ubuntu/webdav/steven_vault/media/xhs/   # 小红书图片

# 查看聚合页
cat /home/ubuntu/webdav/steven_vault/subscription/douyin-hot.md
cat /home/ubuntu/webdav/steven_vault/subscription/bilibili-hot.md

# 查看 daily index
ls /home/ubuntu/webdav/steven_vault/subscription/*-index.md

# 查看 supervisor 状态
cat /home/ubuntu/.dsh/skills/crawl-vm/state/supervisor.json
cat /home/ubuntu/.dsh/skills/crawl-vm/state/recovery.json

# 查看最新跑批事件
tail -f /home/ubuntu/.dsh/skills/crawl-vm/state/run_*.events.jsonl | head
```