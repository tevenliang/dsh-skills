# wps.bookmarks.content

#### 功能说明

查询整篇文档的书签内容

**幂等性**：是 — safe

#### 调用示例

文档查询：

```json
{
  "file_id": "<FILE_ID>",
  "scope": "documents",
  "verb": "query",
  "bookmark_name": "SmokeBookmark_0901"
}
```

#### 参数说明

- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id；与 url、link_id 三选一
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id；与 url、file_id 三选一
- `url` (string, 三选一必填: `url` / `link_id` / `file_id`): 文档 URL；与 link_id、file_id 三选一
- `verb` (string, 必填): 操作类型，固定为 query（查询）。可选值：`query`
- `bookmark_name` (string, 必填): 书签名称

#### 返回值说明

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "bookmark_name": "SmokeBookmark_0901",
    "end": 107,
    "text": "2E_ANCHOR_2026-09-01 baseline paragraph for slice smoke examples.\r"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | number | 0 表示成功 |
| `data` | object | 业务数据 |
| `message` | string | 结果说明 |

