# wps.comments.resolve

## 1. wps.comments.resolve

#### 功能说明

解决在线文字文档批注。

**幂等性**：是 — safe

> index 为 1-based，须先存在批注；可用 wps.comments.list 取真实 index。
> new_text/reply/done 三个动作可独立可选、任意组合。
> 批量处理传 edits 数组（每项 {index, new_text?, reply?, done?}），内部按逆序执行，调用方无需关心索引位移。

#### 调用示例

文档解决：

```json
{
  "file_id": "<FILE_ID>",
  "scope": "documents",
  "verb": "update",
  "index": 1,
  "new_text": "改后正文",
  "reply": "已按建议修改",
  "done": true,
  "author": "灵犀"
}
```

#### 参数说明

- `author` (string, 可选): 批注作者
- `done` (boolean, 可选): 完成状态
- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id；与 url、link_id 三选一
- `index` (number, 可选): 批注索引，从 1 开始，默认 1
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id；与 url、file_id 三选一
- `new_text` (string, 可选): 批注 scope 新文本
- `reply` (string, 可选): 批注回复内容
- `url` (string, 三选一必填: `url` / `link_id` / `file_id`): 文档 URL；与 link_id、file_id 三选一

#### 返回值说明

```json
{
  "code": 0,
  "message": "成功",
  "data": {
    "comment": {
      "author": "未知",
      "date": "2026-09-02T10:00:00.000Z",
      "index": 1,
      "is_reply": false,
      "scope_begin": 1111,
      "scope_end": 1303,
      "scope_text": "改后正文",
      "text": "批注内容"
    }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | number | 0 表示成功 |
| `data` | object | 业务数据 |
| `message` | string | 结果说明 |
