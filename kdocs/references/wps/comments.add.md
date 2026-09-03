# wps.comments.add

## 1. wps.comments.add

#### 功能说明

在在线文字文档中插入批注。

**幂等性**：是 — safe

> 定位批注正文用 range（begin/end）或 paragraph_index 二选一；与 getAllCommentsInfo 的 scope.start/end 回填可实现「与原批注完全相同的选区」。

#### 调用示例

文档插入：

```json
{
  "file_id": "<FILE_ID>",
  "scope": "documents",
  "verb": "insert",
  "text": "批注内容",
  "author": "灵犀"
}
```

#### 参数说明

- `author` (string, 可选): 批注作者
- `begin` (number, 可选): 字符区间起始（与 paragraph_index 二选一）
- `end` (number, 可选): 字符区间结束（与 paragraph_index 二选一）
- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id；与 url、link_id 三选一
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id；与 url、file_id 三选一
- `paragraph_index` (number, 可选): 段落索引，从 1 开始（与 begin/end 二选一）
- `text` (string, 必填): 批注文本
- `url` (string, 三选一必填: `url` / `link_id` / `file_id`): 文档 URL；与 link_id、file_id 三选一

#### 返回值说明

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "comment": {
      "author": "灵犀",
      "date": "2026-09-02T10:00:00.000Z",
      "index": 1,
      "is_reply": false,
      "scope_begin": 1111,
      "scope_end": 1303,
      "scope_text": "原文段落文本",
      "text": "批注内容"
    }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | number | 0 表示成功 |
| `data` | object | 业务数据 |
| `message` | string | 结果说明 |
