# wps.shapes.picture

## 1. wps.shapes.picture

#### 功能说明

插入在线文字文档形状的图片形状。

**幂等性**：是 — safe

> shape_item 应来自 wps.shapes.list

#### 调用示例

示例调用：

```json
{
  "file_id": "file_xxx"
}
```

#### 参数说明

- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id；与 url、link_id 三选一
- `file_path` (string, 可选): file path
- `height` (number, 可选): 高度
- `left` (number, 可选): left
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id；与 url、file_id 三选一
- `top` (number, 可选): top
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
