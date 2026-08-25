# xhs-cli skill vs crawl skill

两者都跟小红书有关,但定位完全不同。

## 核心差异

| 维度 | xhs-cli skill (本) | crawl skill |
|---|---|---|
| **触发** | 关键字 / note_id | watchlist / 单链接 |
| **输出** | chat 即时展示 | 写 vault md |
| **流程** | on-demand(单次) | batch(批跑) |
| **数据流** | search → 渲染 → 完 | download → OCR/ASR → summarize → publish |
| **凭证** | xhs CLI 自带 | `~/.agents/credentials/ominicrawl/xiaohongshu.txt` + xhs CLI + xhs-downloader |
| **触发词** | "小红书搜 X" | "爬取小红书" / "watchlist" |
| **背后工具** | xhs CLI(逆向 API) | xhs CLI(列表) + xhs-downloader(详情) + OCR/ASR |

## 何时用哪个?

### 用 xhs-cli skill 的场景 ✅

- ✅ "小红书搜 XXX" → 临时调研
- ✅ "看看这篇帖子讲了什么" → 单条详情
- ✅ "codex/chatgpt 支付方案有哪些" → 信息收集
- ✅ 不要留底,看完就完
- ✅ 1-10 条结果就够

### 用 crawl skill 的场景 ✅

- ✅ 长期监控某博主 → watchlist
- ✅ 要 OCR 图片里的文字 → 触发 vault OCR
- ✅ 要 ASR 视频 → VM 转录
- ✅ 写 vault 留底供以后搜索
- ✅ 50+ 条批量抓

## 协作方式(最佳实践)

```
1. 用 xhs-cli 临时调研,找到感兴趣的笔记
2. 拿到 note_url,扔给 crawl 走批量流程
3. crawl 抓完写 vault md,后续用 vault-summary/vault-ocr 处理
```

或者反过来:
```
1. crawl watchlist 已经抓了一堆
2. 用 vault 搜索找到某条
3. 想看更多类似 → xhs-cli skill 按关键字搜
```

## 凭证路径不冲突

- **xhs-cli 用**:Chrome cookie(由 `xhs login --cookie-source chrome` 注入到 xhs CLI 自己的存储)
- **crawl 用**:`~/.agents/credentials/ominicrawl/xiaohongshu.txt`(单独文件)

两者**独立**,互不干扰。可以在同一个 Chrome 用同一个账号登录,两个 skill 都跑。

## 性能对比

| 操作 | xhs-cli | crawl |
|---|---|---|
| 搜索 1 个关键字 | ~4s | N/A(crawl 不搜索) |
| 拿 1 条详情 | ~0.5s | ~30s(xhs-downloader) |
| 拿 10 条详情 | ~5s(auto 模式) | ~5 分钟(避风控 sleep) |
| 拿 100 条详情 | 不推荐(风控) | ~50 分钟(稳) |

xhs-cli 走 API 更快,但**有验证码风险**;crawl 走浏览器更稳,但慢。
