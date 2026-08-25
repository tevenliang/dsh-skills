---
name: tencent-yuanbao-search
description: 基于腾讯元宝搜索 API 实时检索互联网信息，支持关键词、站点、时间范围搜索，以及天气/金价/股价/汇率/油价等垂类信息。用于需要联网搜索的场景。
version: 1.0.2
homepage: https://cloud.tencent.com/product/wsa
disable-model-invocation: true
---

# 元宝搜索 (Tencent Yuanbao Search)

基于腾讯云联网搜索 API (WSA) 的实时互联网搜索引擎，为 LLM 提供联网检索能力。

## 认证状态

✅ **已调通** — 环境变量 `TENCENTCLOUD_WSA_APIKEY` 已配置，Key 存于 `~/.zshrc` 或 `.env`（2025-06-20 验证）
✅ **无需重复配置**，重启 terminal 后自动生效

## 2025-06-20 调试记录

- ✅ 基础搜索测试通过（"马刺总决赛 2026 罪人 锅"），响应仅 **1.05秒**，返回 5 条中文结果
- ✅ 中文内容丰富，摘要干净直接可读
- ✅ 环境变量 `TENCENTCLOUD_WSA_APIKEY=sk-f0328fb293dc3b505bdc3bf336d6b0993bd9` 已存在

## 能力

- **关键词搜索**: 搜索互联网公开信息，返回标题、摘要、URL、发布时间、站点
- **时间范围过滤**: 支持 day/week/month/year 时效性过滤
- **垂类信息**: 天气、金价、股价、汇率、油价、贵金属等（mode=1 或 2）
- **站点限定**: 指定域名搜索（如 `sogou.com`）
- **毫秒级响应**，百亿索引内容库，信息自动去噪

## API Key 配置

环境变量 `TENCENTCLOUD_WSA_APIKEY` 已存在，如需重新配置：

```bash
# 临时设置
export TENCENTCLOUD_WSA_APIKEY="你的新key"

# 永久保存到 ~/.zshrc
echo 'export TENCENTCLOUD_WSA_APIKEY="你的新key"' >> ~/.zshrc
source ~/.zshrc
```

获取新 Key: [腾讯云联网搜索控制台](https://console.cloud.tencent.com/wsapi/index?tab=apikey)

## 使用方法

脚本路径: `~/.agents/skills/tencent-yuanbao-search/scripts/websearch.py`

### 基础搜索
```bash
python3 ~/.agents/skills/tencent-yuanbao-search/scripts/websearch.py --query="搜索关键词"
```

### 指定时间范围
```bash
python3 ~/.agents/skills/tencent-yuanbao-search/scripts/websearch.py --query="搜索关键词" --freshness='week'
```
freshness 选项: `day` | `week` | `month` | `year`

### 垂类信息（天气/金价/股价/汇率等）
```bash
python3 ~/.agents/skills/tencent-yuanbao-search/scripts/websearch.py --query="腾讯股价" --mode=2
```
mode: 0=自然检索(默认) | 1=多模态VR | 2=混合

### 指定站点搜索
```bash
python3 ~/.agents/skills/tencent-yuanbao-search/scripts/websearch.py --query="关键词" --site="zhihu.com"
```

## 参数说明

| 参数 | 必填 | 说明 | 示例 |
|------|------|------|------|
| --query | 是 | 搜索关键词 | `--query="AI新闻"` |
| --site | 否 | 限定站点 | `--site="sogou.com"` |
| --mode | 否 | 0=自然检索, 1=多模态VR, 2=混合 | `--mode=2` |
| --freshness | 否 | day/week/month/year | `--freshness='week'` |

## 输出格式

Markdown 格式，每条结果包含标题(可点击链接)、摘要、发布时间、来源站点。

## 故障排查

- **api-key not set**: 检查 `TENCENTCLOUD_WSA_APIKEY` 环境变量
- **服务不可用**: 检查 [腾讯云费用中心](https://console.cloud.tencent.com/expense/overview) 是否欠费
- **服务未开通**: 前往 [联网搜索API控制台](https://console.cloud.tencent.com/wsapi/index?tab=apikey) 开通

## 路径修正（2026-06-26）

- **实际脚本路径**: `~/.agents/skills/tencent-yuanbao-search/scripts/websearch.py`（旧 SKILL.md 写的 `~/.claude/skills/...` 已失效）
- **状态**: ✅ 脚本在位，可直接调用
