# wps.texts.line_spacing

#### 功能说明

按字符区间设置行距

**幂等性**：是 — safe

> paragraph_style.line_spacing 是对象非数字，需传 line_spacing 与 line_spacing_rule（或 spacing_rule 与 spacing_value）；传数字报 unmarshal 错误。
> spacing_rule 只接受数字：0=单倍、1=1.5倍、2=双倍、3=至少(at least)、4=固定(exactly)、5=多倍(multiple)；字符串如 multiple 不生效（解析为 0）。
> spacing_rule=3/4 时 spacing_value 为磅值；=5 时 spacing_value 为倍数（如 1.5）。

#### 调用示例

字符区间设置：

```json
{
  "file_id": "<FILE_ID>",
  "scope": "ranges",
  "begin": 1,
  "end": 74,
  "paragraph_style": {
    "line_spacing": {
      "spacing_rule": "5",
      "spacing_value": 1.5
    }
  }
}
```

#### 参数说明

- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id；与 url、link_id 三选一
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id；与 url、file_id 三选一
- `url` (string, 三选一必填: `url` / `link_id` / `file_id`): 文档 URL；与 link_id、file_id 三选一
- `scope` (string, 必填): 操作范围，固定为 ranges（按字符区间设置）。可选值：`ranges`
- `begin` (number, 可选): 区间起始位置
- `end` (number, 可选): 区间结束位置
- `paragraph_style` (object, 可选): 段落样式对象

#### 返回值说明

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "paragraph_style": {
      "line_spacing": {
        "spacing_rule": "0",
        "spacing_value": 12
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

