# wps.texts.font_batch

#### 功能说明

按字符区间批量设置字体

**幂等性**：是 — safe

> 批量参数名是 font_items（数组）；传 items 报 font_items is required。

#### 调用示例

字符区间设置：

```json
{
  "file_id": "<FILE_ID>",
  "scope": "ranges",
  "begin": 1,
  "end": 74,
  "font_items": [
    {
      "key": "Bold",
      "value": "true"
    }
  ]
}
```

#### 参数说明

- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id；与 url、link_id 三选一
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id；与 url、file_id 三选一
- `url` (string, 三选一必填: `url` / `link_id` / `file_id`): 文档 URL；与 link_id、file_id 三选一
- `scope` (string, 必填): 操作范围，固定为 ranges（按字符区间设置）。可选值：`ranges`
- `begin` (number, 可选): 区间起始位置
- `end` (number, 可选): 区间结束位置
- `font_items` (array, 可选): font items

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

