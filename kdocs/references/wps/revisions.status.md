# wps.revisions.status

## 1. wps.revisions.status

#### 功能说明

设置在线文字文档的修订模式状态。

**幂等性**：是 — safe

#### 调用示例

文档设置：

```json
{
  "file_id": "<FILE_ID>",
  "scope": "documents",
  "verb": "update",
  "enable": true
}
```

#### 参数说明

- `enable` (boolean, 可选): enable
- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id；与 url、link_id 三选一
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id；与 url、file_id 三选一
- `url` (string, 三选一必填: `url` / `link_id` / `file_id`): 文档 URL；与 link_id、file_id 三选一

#### 返回值说明

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "status": true
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | number | 0 表示成功 |
| `data` | object | 业务数据 |
| `message` | string | 结果说明 |
