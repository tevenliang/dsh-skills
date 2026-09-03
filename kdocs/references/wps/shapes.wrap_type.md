# wps.shapes.wrap_type

## 1. wps.shapes.wrap_type

#### 功能说明

设置在线文字文档形状的环绕方式。

**幂等性**：是 — safe

#### 调用示例

文档设置：

```json
{
  "file_id": "<FILE_ID>",
  "scope": "documents",
  "verb": "update",
  "shape_item": "2",
  "wrap_type": 1
}
```

#### 参数说明

- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id；与 url、link_id 三选一
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id；与 url、file_id 三选一
- `shape_item` (string, 可选): shape item
- `url` (string, 三选一必填: `url` / `link_id` / `file_id`): 文档 URL；与 link_id、file_id 三选一
- `wrap_type` (number, 可选): wrap type

#### 返回值说明

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "info": {
      "index": 2,
      "name": "TextBox 5",
      "type": 17
    }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | number | 0 表示成功 |
| `data` | object | 业务数据 |
| `message` | string | 结果说明 |
