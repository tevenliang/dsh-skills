# wps.tocs.data

#### 功能说明

按文档插入目录

> 须先 insert 目录再 query/update/delete；无目录时 query 报 tableOfContents not found。
> insert 需传 upper_level/lower_level 正整数，缺失报 upper_level must be a positive integer。

#### 调用示例

文档插入：

```json
{
  "file_id": "<FILE_ID>",
  "scope": "documents",
  "verb": "insert",
  "lower_level": 1,
  "upper_level": 1
}
```

#### 参数说明

- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id
- `url` (string, 三选一必填: `url` / `link_id` / `file_id`): 文档 URL
- `scope` (string, 必填): 操作范围，固定为 documents（按文档设置）。可选值：`documents`
- `verb` (string, 必填): 操作类型，固定为 insert（插入）。可选值：`insert`
- `lower_level` (number, 可选): 结束标题级别
- `upper_level` (number, 可选): 起始标题级别

#### 返回值说明

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "toc_index": 1
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | number | 0 表示成功 |
| `data` | object | 业务数据 |
| `message` | string | 结果说明 |

