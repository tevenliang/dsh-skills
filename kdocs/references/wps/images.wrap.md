# wps.images.wrap

## 1. wps.images.wrap

#### 功能说明

设置在线文字文档图片的环绕方式。

**幂等性**：是 — safe

> index 是图片在文档中的当前序号（从 1 起），插入/删除图片后序号会变化；操作前先调 wps.images.list 获取最新 index，勿沿用旧序号。

#### 调用示例

示例调用：

```json
{
  "file_id": "file_xxx"
}
```

#### 参数说明

- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id；与 url、link_id 三选一
- `index` (number, 必填): 索引，从 1 开始
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id；与 url、file_id 三选一
- `url` (string, 三选一必填: `url` / `link_id` / `file_id`): 文档 URL；与 link_id、file_id 三选一
- `wrap_type` (number, 可选): 环绕方式

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
