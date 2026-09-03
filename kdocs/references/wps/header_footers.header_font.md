# wps.header_footers.header_font

## 1. wps.header_footers.header_font

#### 功能说明

设置在线文字文档页眉的字体。

**幂等性**：是 — safe

#### 调用示例

文档设置：

```json
{
  "file_id": "<FILE_ID>",
  "scope": "documents",
  "verb": "update",
  "font_style": {
    "bold": true
  },
  "header_footer_type": 1,
  "key": "Bold",
  "section_index": 1,
  "value": "true"
}
```

#### 参数说明

- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id；与 url、link_id 三选一
- `font_style` (object, 可选): 字体样式对象
- `header_footer_type` (number, 可选): header footer type
- `key` (string, 可选): 属性名
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id；与 url、file_id 三选一
- `section_index` (number, 可选): 节索引，从 1 开始
- `url` (string, 三选一必填: `url` / `link_id` / `file_id`): 文档 URL；与 link_id、file_id 三选一
- `value` (string, 可选): 属性值

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
