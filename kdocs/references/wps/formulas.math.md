# wps.formulas.math

## 1. wps.formulas.math

#### 功能说明

插入在线文字文档公式。

**幂等性**：是 — safe

> 段落插入用 paragraph_index（1-based）；区间插入用 begin/end（0-based），可由 wps.texts.search 返回的 ranges 回填。

#### 调用示例

示例调用：

```json
{
  "file_id": "file_xxx"
}
```

#### 参数说明

- `begin` (number, 可选): 区间起始位置
- `display_type` (number, 可选): display type
- `end` (number, 可选): 区间结束位置
- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id；与 url、link_id 三选一
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id；与 url、file_id 三选一
- `paragraph_index` (number, 可选): 段落索引，从 1 开始
- `text` (string, 必填): 文本内容
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
