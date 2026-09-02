---
name: tavily-search
description: Tavily AI 搜索
metadata:
  openclaw:
    requires:
      env:
        - TAVILY_API_KEY
    primaryEnv: TAVILY_API_KEY
version: 1.0.0
homepage: https://tavily.com
disable-model-invocation: true
---

# Tavily AI Search

AI 优化的搜索引擎，专为 LLM 设计。相比传统搜索 API，提供 AI 答案摘要、干净结构化结果、域名过滤、原始内容提取。

## 认证状态

✅ **已调通** — Key 已保存到 `~/.agents/credentials/tavily.json`（2025-06-20 验证）
✅ **无需重复配置**，Key 长期有效

## 核心能力

- **AI 答案摘要**: 从搜索结果自动合成摘要
- **双模式**: `basic`(1-2s, 快速) / `advanced`(5-10s, 深度)
- **新闻搜索**: `--topic news` 搜索最近 7 天新闻
- **域名过滤**: 限定/排除特定网站
- **图片搜索**: `--images` 获取相关图片
- **原始内容**: `--raw-content` 提取网页全文

## 使用方法

```bash
python3 /home/ubuntu/.dsh/skills/tavily-search/scripts/tavily_search.py "搜索关键词" [选项]
```
