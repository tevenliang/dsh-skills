# wps.texts.search

## 1. wps.texts.search

#### 功能说明

在在线文字文档中搜索文本。

> 全文定位工具：按文本查找返回 0-based 字符区间（ranges）。在调用任何 ranges 类插入/设置工具（wps.texts.content、wps.bookmarks.insert、wps.hyperlinks.insert、wps.comments.range_insert、wps.fields.by_range 等）之前，宜先用本工具拿到 begin/end。
> 返回的 ranges 为 0-based 字符区间（begin/end）；可直接回填到各 ranges 类插入/设置工具（如 wps.texts.content / wps.bookmarks.insert / wps.comments.range_insert）的 begin/end 参数，实现「先定位再写入」。
> 找不到匹配文本时 ranges 为空数组；先确认文档内容与 find_text 一致再调用写入类工具。
> L1 由 URL verb 区分能力，请求体勿带 properties（见 ein DocsMeta.OmitProperties）

#### 调用示例

文档搜索：

```json
{
  "file_id": "<FILE_ID>",
  "scope": "documents",
  "verb": "search",
  "find_text": "SMOKE_SLICE_ANCHOR_2026-09-01",
  "is_all": true
}
```

#### 参数说明

- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id；与 url、link_id 三选一
- `find_text` (string, 必填): 查找文本
- `is_all` (boolean, 可选): 是否查找全部
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id；与 url、file_id 三选一
- `url` (string, 三选一必填: `url` / `link_id` / `file_id`): 文档 URL；与 link_id、file_id 三选一

#### 返回值说明

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "ranges": [
      {
        "begin": 1111,
        "end": 1303
      }
    ]
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | number | 0 表示成功 |
| `data` | object | 业务数据 |
| `message` | string | 结果说明 |
