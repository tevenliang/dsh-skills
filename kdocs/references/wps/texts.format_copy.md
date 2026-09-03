# wps.texts.format_copy

## 1. wps.texts.format_copy

#### 功能说明

将源段落格式复制到目标段落范围（格式刷）。

**幂等性**：是 — safe

#### 调用示例

段落设置：

```json
{
  "file_id": "<FILE_ID>",
  "scope": "paragraphs",
  "verb": "update",
  "format_items": [
    {
      "key": "Bold",
      "value": "true"
    }
  ],
  "source_paragraph": 1,
  "target_end": 2,
  "target_start": 2
}
```

#### 参数说明

- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id；与 url、link_id 三选一
- `format_items` (array, 可选): 高级：直接传 source_paragraph/target_start/target_end 键值对，与上述三参数二选一
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id；与 url、file_id 三选一
- `source_paragraph` (number, 必填): 源段落索引，从 1 开始
- `target_end` (number, 必填): 目标结束段落索引，从 1 开始
- `target_start` (number, 必填): 目标起始段落索引，从 1 开始
- `url` (string, 三选一必填: `url` / `link_id` / `file_id`): 文档 URL；与 link_id、file_id 三选一

#### 返回值说明

```json
{
  "code": 0,
  "message": "成功",
  "data": {}
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | number | 0 表示成功 |
| `data` | object | 业务数据 |
| `message` | string | 结果说明 |
