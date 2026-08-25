---
name: xhs-cli
metadata:
  version: 1.0.0
  author: Codex (Steven's setup)
description: 小红书(xiaohongshu) on-demand 关键字搜索 + 详情抓取工具,基于 xhs CLI
  (xiaohongshu-cli v0.6.4)。**返回 chat 即用, 不写 vault md**, 与 crawl skill (批量写
  vault) 是两条独立路径。
disable-model-invocation: true
---

# xhs-cli — 小红书即时搜索 skill

## 这是什么

`xhs CLI` 是通过 `uv tool install xiaohongshu-cli` 安装的 Python 工具(v0.6.4),从 Chrome
读 cookie 登录,逆向小红书 API。本 skill 围绕它封装了:

1. **关键字搜索** → 立刻返回 markdown 表格
2. **详情抓取** → 拿正文 + 图片列表 + 互动数据
3. **图片本地缓存** → 解决 Codex 不渲染远程 URL 的问题

## 跟 crawl 的差异

| 维度 | **crawl** (已有) | **xhs-cli** (本 skill) |
|---|---|---|
| 触发 | watchlist 监控 / 单链接 | **on-demand 关键字** |
| 输出 | 写 vault md 文件 | **直接渲染给 chat** |
| 流程 | batch(批量 + 后台) | **on-demand(单次)** |
| 详情抓取 | xhs-downloader(避滑块验证码) | xhs CLI read(单次手动 OK) |
| 凭证 | `~/.agents/credentials/ominicrawl/xiaohongshu.txt` | **xhs CLI 自带(Chrome cookie)** |

> 💡 **底层关系**:crawl 也用 xhs CLI 做列表阶段(走 `user-posts`),不走 search。本 skill
> 是 xhs CLI 的 on-demand 封装层。

## 触发词

| 你说 | 程序调 |
|------|--------|
| 「小红书搜 XXX」「xhs 搜 XXX」「xhs search XXX」 | `xhs_search.py search` |
| 「小红书看这篇帖子」「xhs detail」 | `xhs_search.py detail` |
| 「小红书搜 XXX 并展示正文+图」「xhs auto XXX」 | `xhs_search.py auto` |

## 前置条件

```bash
# 1. 安装 xhs CLI (一次性)
uv tool install xiaohongshu-cli

# 2. 在 Chrome 登录 xiaohongshu.com,然后:
xhs login --cookie-source chrome

# 3. 一键体检
bash ~/.agents/skills/xhs-cli/scripts/check_setup.sh
```

## 快速开始

```bash
# 1. 关键字搜索,返回表格
python3 ~/.agents/skills/xhs-cli/scripts/xhs_search.py search "咖啡" --limit 5

# 2. 搜索 + 下载封面图(供 Codex 显示)
python3 ~/.agents/skills/xhs-cli/scripts/xhs_search.py search "咖啡" --limit 3 --render

# 3. 读单条详情
python3 ~/.agents/skills/xhs-cli/scripts/xhs_search.py detail <note_id> \
    --xsec-token "<token>" --render --max-images 9

# 4. 一条龙: 搜索 → 自动取前 N 条详情 → 全部带图渲染
python3 ~/.agents/skills/xhs-cli/scripts/xhs_search.py auto "codex免费试用" \
    --limit 2 --max-images 4 --render
```

## 子命令详解

### `search <keyword>`
按关键字搜索,返回 markdown 表格。

参数:
- `keyword`: 搜索词(中文 OK)
- `--limit N`: 最多返回 N 条(默认 10)
- `--sort`: `general` / `popular` / `latest`(默认 general)
- `--page N`: 翻页
- `--render`: 下载封面图到本地(供 Codex 显示)
- `--out-dir`: 自定义图片输出目录(默认 `~/Documents/agent_spaces/output/xhs_images/`)

### `detail <note_id>`
读单条笔记的完整内容(正文 + 全部图片 URL + 互动数据 + 标签)。

参数:
- `note_id`: 笔记 ID(从 search 结果拿)
- `--xsec-token`: 该笔记的安全 token(从 search 结果的 `xsec_token` 字段拿)
- `--render`: 下载图片到本地
- `--max-images N`: 最多渲染几张图(剩余本地保留)

### `auto <keyword>`
**最常用**。一条龙: search → 自动取 top N → 每条调 read → 渲染带图 markdown。

参数:
- `keyword`: 搜索词
- `--limit N`: 自动取前 N 条详情(默认 3)
- `--sort`: 排序
- `--render` / `--no-render`: 是否下载图
- `--max-images N`: 每条最多几张图
- `--out-dir`: 图片目录
- `--sleep N`: 每条 read 之间间隔秒数(防滑块验证码,默认 3)

## 输出位置

- **图片默认输出:** `~/Documents/agent_spaces/output/xhs_images/`
- 命名规则:`<URL SHA256 前 16 位>_<时间戳>.<ext>`(SHA256 缓存,同一张图不重复下载)
- 文件夹可定期清理

## 风控提醒

- `xhs search` 不撞验证码,放心批量
- `xhs read` 单次手动 OK,但**连续 4-5 次会触发滑块验证码**
- `--with-content` 模式默认 sleep 3s,可调
- 风控后建议等 5-10 分钟再试

## 文件清单

```
~/.agents/skills/xhs-cli/
├── SKILL.md                          ← 你正在看
├── scripts/
│   ├── xhs_search.py                 ← 主工具(CLI 入口)
│   └── check_setup.sh                ← 安装体检脚本
├── examples/
│   ├── 01-search-keyword.md          ← 示例:简单搜索
│   ├── 02-detail-with-images.md      ← 示例:带图详情
│   ├── 03-auto-mode.md               ← 示例:一条龙
│   └── 04-common-commands.md         ← 常用命令速查
└── references/
    ├── xhs-cli-commands.md           ← xhs CLI 全部子命令参考
    ├── vs-crawl.md                   ← 跟 crawl skill 的取舍
    ├── vs-xiaohongshu-skills.md      ← 跟浏览器自动化的取舍
    └── troubleshooting.md            ← 常见问题(验证码/IP/登录)
```

## 已知限制

1. **逆向 API,违反小红书 ToS** — 账号有封禁风险,别用主号批量
2. **需要 Chrome 已登录** — xhs CLI 从 Chrome 读 cookie
3. **search 返回的 xsec_token 有时效** — 长时间不调 read 可能失效
4. **xhs read 不返回视频流** — 视频笔记只能拿到封面图

## 升级历史

- **v1.0.0 (2026-08-16)**: 初始版本,从 crawl/tools/xhs_search.py 迁移并完善
  - 修复 JSON 解析 bug(输出超过 50000 字符时找错起点)
  - 修复作者显示问题(search 返回 `nick_name`,read 返回 `nickname`)
  - 增加 SHA256 图片缓存
  - 增加 sub-command 化设计(search/detail/auto)
