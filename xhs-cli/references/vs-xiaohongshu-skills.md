# xhs-cli skill vs xiaohongshu-skills (浏览器自动化)

这是两个**完全不同的技术路线**,针对不同场景。

## 技术路线对比

| 维度 | **xhs-cli**(本 skill) | **xiaohongshu-skills** (autoclaw-cc) |
|---|---|---|
| **底层技术** | 逆向 API(subprocess) | Chrome 扩展 + Python 脚本 |
| **是否需要 Chrome 开着** | ❌ 不需要(只读 cookie) | ✅ **必须开 Chrome + 装扩展** |
| **是否真实浏览器** | ❌ HTTP API 调用 | ✅ **真实浏览器自动化** |
| **是否支持 headless** | ✅ 天然 headless(CLI) | ❌ 必须有浏览器窗口 |
| **风控表现** | 批量 4-5 次会撞滑块 | 风控容忍度更高 |
| **支持操作** | 几乎全部(发布/评论/搜索) | 几乎全部 |
| **安装** | `uv tool install` | `git clone` + Chrome 扩展 |

## 详细对比

### xhs-cli

✅ **优点**:
- 快(HTTP API,不走渲染)
- 天然 headless,服务器/后台跑 OK
- 安装简单(一行命令)
- Codex 调用方便(subprocess)

❌ **缺点**:
- 逆向 API,违反 ToS,有封号风险
- 批量会撞滑块验证码
- 视频流可能拿不到(API 限制)

### xiaohongshu-skills (Chrome 扩展)

✅ **优点**:
- 用真实浏览器,行为更像真人
- 风控容忍度更高(已经是真人登录态)
- 能拿视频流(浏览器能解码)
- 支持复杂交互(拖拽、上传)

❌ **缺点**:
- 必须 Chrome 开着 + 扩展挂着
- 不能 headless(没办法放后台)
- 安装复杂(Chrome 扩展)
- 跟 Codex 集成需要 WebSocket bridge(bridge_server.py)

## 何时用哪个?

| 场景 | 推荐 |
|---|---|
| Codex on-demand 查询关键字 | **xhs-cli** |
| 批量跑批、watchlist 监控 | **crawl**(用 xhs-downloader) |
| 在 iPhone/Mac 上手动运营 | **xiaohongshu-skills** |
| 服务器后台跑批 | **xhs-cli** |
| 模拟真人复杂操作(点赞/评论/发布) | **xiaohongshu-skills** |
| 临时调研 + 立刻看 | **xhs-cli**(本 skill) |

## 注意事项

两个 skill **不冲突**,可以同时装:

```bash
# xhs-cli skill
~/.agents/skills/xhs-cli/

# xiaohongshu-skills
~/.codex/skills/xiaohongshu-skills/  # 或 ~/.openclaw/skills/

# 凭证独立
~/.local/bin/xhs login --cookie-source chrome          # xhs-cli 用
xiaohongshu-skills/extension/                          # Chrome 扩展
```

## 推荐组合

```
LLM API 聚合开发者 (你的画像):
├── xhs-cli (本 skill): on-demand 调研、临时搜索、Codex 即时调用
├── crawl: 长期监控某些博主、写 vault 留底
└── 都不装 xiaohongshu-skills: 跟 LLM API 业务无关
```
