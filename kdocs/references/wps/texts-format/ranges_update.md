# wps.texts.format

#### 功能说明

按字符区间设置格式

**幂等性**：是 — safe

> key 与 value 必须成对传（key=属性名如 Bold，value=属性值如 true）；只传 paragraph_style 报 key and value required。

#### 调用示例

字符区间设置：

```json
{
  "file_id": "<FILE_ID>",
  "scope": "ranges",
  "begin": 1,
  "end": 74,
  "key": "Bold",
  "value": "true"
}
```

#### 参数说明

- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id；与 url、link_id 三选一
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id；与 url、file_id 三选一
- `url` (string, 三选一必填: `url` / `link_id` / `file_id`): 文档 URL；与 link_id、file_id 三选一
- `scope` (string, 必填): 操作范围，固定为 ranges（按字符区间设置）。可选值：`ranges`
- `begin` (number, 可选): 区间起始位置
- `end` (number, 可选): 区间结束位置
- `key` (string, 可选): 属性名
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

