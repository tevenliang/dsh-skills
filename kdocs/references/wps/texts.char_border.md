# wps.texts.char_border

## 1. wps.texts.char_border

#### 功能说明

设置在线文字文档文本的字符边框。

**幂等性**：是 — safe

#### 调用示例

字符区间设置：

```json
{
  "file_id": "<FILE_ID>",
  "scope": "ranges",
  "verb": "update",
  "begin": 1,
  "char_border_color": 255,
  "char_border_line_style": 1,
  "char_border_line_width": 1,
  "end": 74
}
```

#### 参数说明

- `begin` (number, 可选): 区间起始位置
- `char_border_color` (number, 可选): char border color
- `char_border_line_style` (number, 可选): char border line style
- `char_border_line_width` (number, 可选): char border line width
- `end` (number, 可选): 区间结束位置
- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id；与 url、link_id 三选一
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id；与 url、file_id 三选一
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
