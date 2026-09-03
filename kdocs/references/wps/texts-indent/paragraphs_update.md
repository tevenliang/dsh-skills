# wps.texts.indent

#### 功能说明

按段落设置缩进

**幂等性**：是 — safe

> paragraph_style.indent 需对象，缺失报 paragraph_style.indent required。
> indent_type 只接受数字：1=左缩进、2=右缩进、3=首行缩进；字符串如 first_line 不生效（解析为 0）。
> unit 只接受数字：1=磅(point)、2=字符(character)；字符串如 char 不生效（解析为 0）。
> indent_value 为缩进量数值，配合 unit 解释。

#### 调用示例

段落设置：

```json
{
  "file_id": "<FILE_ID>",
  "scope": "paragraphs",
  "paragraph_index": 1,
  "paragraph_style": {
    "indent": {
      "indent_type": "3",
      "indent_value": 2,
      "unit": "2"
    }
  }
}
```

#### 参数说明

- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id；与 url、link_id 三选一
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id；与 url、file_id 三选一
- `url` (string, 三选一必填: `url` / `link_id` / `file_id`): 文档 URL；与 link_id、file_id 三选一
- `scope` (string, 必填): 操作范围，固定为 paragraphs（按段落设置）。可选值：`paragraphs`
- `paragraph_index` (number, 可选): 段落索引，从 1 开始
- `paragraph_style` (object, 可选): 段落样式对象

#### 返回值说明

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "paragraph_style": {
      "indent": {
        "indent_type": "first_line",
        "indent_value": 2,
        "unit": "char"
      }
    }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | number | 0 表示成功 |
| `data` | object | 业务数据 |
| `message` | string | 结果说明 |

