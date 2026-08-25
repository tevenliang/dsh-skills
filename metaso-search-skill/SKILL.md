---
search: false
name: metaso-search
description: Search the web using Metaso AI Search API. Use for live
  information, documentation, or research topics.
metadata:
  openclaw:
    emoji: 🔍
    requires:
      bins:
        - python
      env:
        - METASO_API_KEY
    primaryEnv: METASO_API_KEY
disable-model-invocation: true
---

# Metaso Search

Search the web via Metaso AI Search API.

## Usage

```bash
python skills/metaso-search/scripts/search.py '<JSON>'
```

## Request Parameters

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| q | str | yes | - | Search query |
| scope | str | no | webpage | Search scope: webpage, news, paper, etc. |
| size | int | no | 10 | Number of results (1-50) |
| page | int | no | 1 | Page number |
| conciseSnippet | bool | no | false | Return concise snippet |
| includeSummary | bool | no | false | Include AI summary |
| includeRawContent | bool | no | false | Fetch raw content from sources |

## Examples

```bash
# Basic search
python scripts/search.py '{"q":"OpenClaw AI"}'

# With options
python scripts/search.py '{
  "q": "人工智能最新进展",
  "size": 5,
  "includeSummary": true
}'
```

## API Reference

- **官方文档**: https://metaso.cn/search-api/playground
- **Endpoint**: `https://metaso.cn/api/v1/search`
- **Method**: POST
- **Auth**: Bearer token in `Authorization` header
- **Content-Type**: `application/json`

## Request Example

```bash
curl --location 'https://metaso.cn/api/v1/search' \
--header 'Authorization: Bearer YOUR_API_KEY' \
--header 'Accept: application/json' \
--header 'Content-Type: application/json' \
--data '{
  "q": "搜索关键词",
  "scope": "webpage",
  "size": 10,
  "includeSummary": false,
  "includeRawContent": false,
  "conciseSnippet": false
}'
```

## Response Example

```json
{
  "credits": 3,
  "searchParameters": {
    "q": "搜索关键词",
    "scope": "webpage",
    "size": 10
  },
  "webpages": [
    {
      "title": "标题",
      "link": "https://example.com",
      "snippet": "摘要内容",
      "score": "high",
      "date": "2026-03-22"
    }
  ],
  "total": 25
}
```

## Current Status

✅ Ready to use

---

## 带引用标注的搜索（推荐）

`metaso_search_with_citations.py` 在原始 API 基础上增加了编号引用，支持两种模式：

### plain 模式（默认，无需 LLM）

```bash
python3 scripts/metaso_search_with_citations.py "关键词" -s 8 -m plain
```

输出示例：
```
# 秘塔搜索：Similarweb公司介绍
共找到约 29 条结果
---
**[1] SimilarWeb概述**
   URL: https://...
   日期: 2023年09月01日
   摘要: ...

**[2] SimilarWeb 核心介绍**
   URL: https://...
   ...
```

### llm 模式（需要 LLM API）

```bash
python3 scripts/metaso_search_with_citations.py "Similarweb竞品分析" -s 6 -m llm
```

输出：先调用 bailian-cli (qwen3.7-plus) 生成带 `[1][2]` 编号引用的结构化答案，末尾附原始链接列表。

### 参数说明

| 参数 | 说明 |
|------|------|
| `关键词` | 搜索词（位置参数） |
| `-s N` | 结果数量，默认 8 |
| `-m plain/llm` | plain=纯格式，llm=LLM增强 |
| `-f json/text` | 输出格式，默认 text |

**依赖**：`METASO_API_KEY` 环境变量；llm 模式需要 `bl text chat`（bailian-cli）或 `OPENROUTER_API_KEY`。
