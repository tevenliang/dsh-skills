# wps.shapes.basic

## 1. wps.shapes.basic

#### 功能说明

插入在线文字文档形状的基本形状。

**幂等性**：是 — safe

#### 调用示例

文档插入：

```json
{
  "file_id": "<FILE_ID>",
  "scope": "documents",
  "verb": "insert",
  "height": 50,
  "left": 72,
  "shape_type": 1,
  "top": 72,
  "width": 100
}
```

#### 参数说明

- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id；与 url、link_id 三选一
- `height` (number, 可选): 高度
- `left` (number, 可选): left
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id；与 url、file_id 三选一
- `shape_type` (number, 可选): shape type
- `top` (number, 可选): top
- `url` (string, 三选一必填: `url` / `link_id` / `file_id`): 文档 URL；与 link_id、file_id 三选一
- `width` (number, 可选): 宽度

#### 返回值说明

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "info": {
      "height": 50,
      "index": 3,
      "left": 72,
      "name": "Rectangle 3",
      "top": 72,
      "type": 1,
      "width": 100
    }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | number | 0 表示成功 |
| `data` | object | 业务数据 |
| `message` | string | 结果说明 |
