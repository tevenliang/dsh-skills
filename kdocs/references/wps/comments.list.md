# wps.comments.list

## 1. wps.comments.list

#### 功能说明

查询在线文字文档批注的列表。

**幂等性**：是 — safe

#### 调用示例

文档查询：

```json
{
  "file_id": "<FILE_ID>",
  "scope": "documents",
  "verb": "query"
}
```

#### 参数说明

- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id；与 url、link_id 三选一
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id；与 url、file_id 三选一
- `url` (string, 三选一必填: `url` / `link_id` / `file_id`): 文档 URL；与 link_id、file_id 三选一

#### 返回值说明

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "comments": [
      {
        "author": "未知",
        "date": "2026-09-01 11:16:34",
        "index": 1,
        "is_reply": false,
        "scope_begin": 0,
        "scope_end": 85,
        "scope_text": "SE_ANCHOR_2026-09-01 baseline paragraph for slice smoke examples.",
        "text": "smoke comment anchor\r"
      }
    ]
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | number | 0 表示成功 |
| `data` | object | 业务数据 |
| `message` | string | 结果说明 |
