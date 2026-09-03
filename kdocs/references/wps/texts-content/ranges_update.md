# wps.texts.content

#### 功能说明

按字符区间设置文本内容

**幂等性**：是 — safe

> A/C gap: documents insert/delete TEXT_CONTENT
> begin 必须为正整数（≥1），传 0 报 begin must be a positive integer。

#### 调用示例

字符区间设置：

```json
{
  "file_id": "<FILE_ID>",
  "scope": "ranges",
  "verb": "update",
  "begin": 1,
  "content": "smoke example text",
  "end": 74
}
```

#### 参数说明

- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id；与 url、link_id 三选一
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id；与 url、file_id 三选一
- `url` (string, 三选一必填: `url` / `link_id` / `file_id`): 文档 URL；与 link_id、file_id 三选一
- `scope` (string, 必填): 操作范围，固定为 ranges（按字符区间设置）。可选值：`ranges`
- `verb` (string, 必填): 操作类型，固定为 update（更新）。可选值：`update`
- `begin` (number, 可选): 区间起始位置
- `content` (string, 可选): 文本内容
- `end` (number, 可选): 区间结束位置

#### 返回值说明

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "content": "smoke example text"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | number | 0 表示成功 |
| `data` | object | 业务数据 |
| `message` | string | 结果说明 |

