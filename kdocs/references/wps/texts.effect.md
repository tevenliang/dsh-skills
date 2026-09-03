# wps.texts.effect

## 1. wps.texts.effect

#### 功能说明

设置在线文字文档文本的文字效果（阴影/隐藏等）。

**幂等性**：是 — safe

#### 调用示例

字符区间设置：

```json
{
  "file_id": "<FILE_ID>",
  "scope": "ranges",
  "verb": "update",
  "begin": 1,
  "end": 74,
  "text_effect_all_caps": true,
  "text_effect_double_strike_through": true,
  "text_effect_emboss": true,
  "text_effect_engrave": true,
  "text_effect_hidden": true,
  "text_effect_shadow": true,
  "text_effect_small_caps": true,
  "text_effect_strike_through": true
}
```

#### 参数说明

- `begin` (number, 可选): 区间起始位置
- `end` (number, 可选): 区间结束位置
- `file_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 文件 id；与 url、link_id 三选一
- `link_id` (string, 三选一必填: `url` / `link_id` / `file_id`): 分享 id；与 url、file_id 三选一
- `text_effect_all_caps` (boolean, 可选): 全大写 AllCaps
- `text_effect_double_strike_through` (boolean, 可选): 双删除线 DoubleStrikeThrough
- `text_effect_emboss` (boolean, 可选): text effect emboss
- `text_effect_engrave` (boolean, 可选): 阴文 Engrave
- `text_effect_hidden` (boolean, 可选): text effect hidden
- `text_effect_shadow` (boolean, 可选): text effect shadow
- `text_effect_small_caps` (boolean, 可选): text effect small caps
- `text_effect_strike_through` (boolean, 可选): text effect strike through
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
