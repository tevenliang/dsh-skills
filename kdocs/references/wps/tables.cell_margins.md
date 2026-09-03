# wps.tables.cell_margins

## 1. wps.tables.cell_margins

#### 功能说明

设置在线文字文档表格的单元格边距。

**幂等性**：是 — safe

#### 调用示例

文档设置：

```json
{
  "file_id": "<FILE_ID>",
  "scope": "documents",
  "verb": "update",
  "col": 1,
  "datas": [],
  "height": 20,
  "row": 1,
  "table_index": 1,
  "width": 72
}
```

#### 参数说明

- `col` (number, 可选): 列号
- `datas` (array, 可选): 批量数据数组
- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id；与 url、link_id 三选一
- `height` (number, 可选): 高度
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id；与 url、file_id 三选一
- `row` (number, 可选): 行号
- `table_index` (number, 必填): 表格索引，从 1 开始
- `url` (string, 三选一必填: `url` / `link_id` / `file_id`): 文档 URL；与 link_id、file_id 三选一
- `width` (number, 可选): 宽度

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
