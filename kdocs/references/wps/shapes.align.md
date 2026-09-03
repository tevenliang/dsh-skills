# wps.shapes.align

## 1. wps.shapes.align

#### 功能说明

设置在线文字文档形状的对齐。

**幂等性**：是 — safe

> group/align/distribute 需至少 2 个形状；shape_names 来自 wps.shapes.list。

#### 调用示例

文档设置：

```json
{
  "file_id": "<FILE_ID>",
  "scope": "documents",
  "verb": "update",
  "align_cmd": 1,
  "relative_to_page": false,
  "shape_names": [
    "Rectangle 1",
    "Rectangle 2"
  ]
}
```

#### 参数说明

- `align_cmd` (number, 可选): align cmd
- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id；与 url、link_id 三选一
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id；与 url、file_id 三选一
- `relative_to_page` (boolean, 可选): relative to page
- `shape_names` (array, 可选): shape names
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
