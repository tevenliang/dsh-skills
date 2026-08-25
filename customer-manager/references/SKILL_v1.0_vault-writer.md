---
name: customer-update
description: 客户资料新建/更新 skill。AI 对话中把网上搜索的客户资料解析为 22 字段结构 → dry-run 预览 → 写入 vault md。**与 customer-manager 严格同源字段模型**(复用 shared_map.FIELD_DEFS)。**不写 Excel**(由 customer-manager sync 推回)。**默认 upsert 守卫**(不破坏已有数据)。不支持批量,一次一个客户。触发词:"新建客户"/"更新客户"/"录入客户"/"加客户"/"客户信息"。
version: 1.0
author: Steven Liang
platforms: [macos, linux]
changelog:
  - 1.0 (2026-08-05): 初始版本。新建/更新客户资料,严格复用 customer-manager 22 字段模型,AI 对话中解析后调脚本写 vault,默认 upsert 守卫,行业/销售阶段 enum 校验。
---

# customer-update — 客户资料新建/更新

> **职责单一**：写 vault md 客户基础资料。**不写 Excel**(留给 customer-manager),**不写跟进记录/下一步/联系人**(留给 write_note.py)。

## 数据模型（严格与 customer-manager 对齐）

22 frontmatter 字段 + 1 vault 专属（关联issue）= 来自 `customer-manager/scripts/shared_map.py`：
- A 客户名称 / B 行业 / C 销售阶段 / D 客户标签
- E 联系人 / F 跟进记录 / G 关联文档
- H 下一步计划 / I 下一步行动 / J 总结
- K 公司简介 / L 产品服务 / M 财务状况
- N 客户群体 / O 营收 / P 人数
- Q 网站 / R 地址 / S 竞争对手 / T 城市
- U 备注 / V 更新日期

> 单源真源 = `shared_map.FIELD_DEFS`,**任何字段新增/重命名必须先改 customer-manager**。

## 能力

| 命令 | 用途 |
|---|---|
| `new` | 新建客户(22 字段全空骨架 + 更新日期=今天) |
| `update` | 更新已有客户(按字段名覆盖,缺字段不动) |
| `set` | 单一字段 set(CLI 形式,适合快速改一个字段) |
| `apply` | JSON 一次性导入(AI 解析后调此) |

> **不支持批量**。一次查一家,一家新建/更新。

## 默认写入策略

| 字段类型 | 字段 | 策略 |
|---|---|---|
| **单值** | 行业/销售阶段/客户标签/城市/营收/人数/网站/地址/下一步计划/下一步行动/更新日期 | 覆盖 |
| **多行** | 联系人/跟进记录/关联文档/总结/公司简介/产品服务/财务状况/客户群体/竞争对手/备注 | **upsert 守卫**(源端空 → 不清对端) |

**upsert 守卫语义**：
- 源端字段有内容 → 覆盖对端
- 源端字段空 → 保留对端已有值
- 例外:`更新日期` 永远刷成今天

加 `--replace` 强制覆盖;加 `--append` 追加(仅多行字段)。

## 校验

- **行业 enum** 白名单从 `customer-manager/scripts/vault_health.py` 的 `INDUSTRIES` 拉取
- **销售阶段 enum** 白名单从 `STAGES` 拉取
- **客户名称** 必填
- 模糊匹配 top 3 有同名的 → 列出候选让用户选

## 命令速查

```bash
cd ~/.agents/skills/PRODUCTIVITY/customer-update/scripts

# 1. 新建客户(22 字段全空骨架)
python3 customer_update.py new --name "深圳某某科技有限公司" --apply

# 2. AI 解析后从 JSON 导入(推荐)
python3 customer_update.py apply --from-json /tmp/customer.json --apply

# 3. 单一字段 set
python3 customer_update.py set \
  --customer "深圳鎏信" \
  --field 行业 --value "人工智能" \
  --apply

# 4. dry-run 预览(默认)
python3 customer_update.py new --name "XXX" --field 行业=AI
```

**JSON 输入格式**(AI 解析后产出):
```json
{
  "客户名称": "深圳鎏信科技有限公司",
  "行业": "人工智能",
  "销售阶段": "建联",
  "公司简介": "...",
  "产品服务": "...",
  "联系人": "张三 13912345678 老板",
  "客户标签": "重点客户,AI"
}
```

## 工作流(AI 主导)

```
[1] 用户在对话中粘贴元宝/企查查结果 或 自然语言
    例:"新建客户 深圳市某某科技有限公司:
        行业: 人工智能
        销售阶段: 建联
        公司简介: 成立于2018年..."
  ↓
[2] AI 解析成 22 字段 JSON
  ↓
[3] 模糊匹配 vault 是否存在
    ├─ 找到 → 走 update,展示 diff
    └─ 没找到 → 走 new,展示 22 字段填写
  ↓
[4] 校验:行业 enum / 销售阶段 enum / 客户名称
  ↓
[5] dry-run 预览
  ↓
[6] 用户回复 "apply" / "改 XXX"
  ↓
[7] 写 vault md,更新日期=今天
  ↓
[8] 提示:"运行 customer-manager sync.py --apply 推回 Excel"
```

## 触发词

```
新建客户 / 加个客户 / 加客户 / 录入客户
更新客户 / 改客户资料 / 客户信息
```

## 与 customer-manager 关系

```
customer-update:  raw text/AI 解析 → vault md (写)
customer-manager: vault md ↔ Excel (同步)
```

- **本 skill 不写 Excel**——避免与 sync 引擎逻辑重复
- 写完 vault 后 `更新日期` 翻到今天,下次 sync 自然胜出
- 提示用户跑 `python3 ~/.../customer-manager/scripts/sync.py --apply` 推回 Excel

## 安全策略

1. **dry-run 必走**:默认预览,加 `--apply` 才写盘
2. **upsert 守卫**:缺字段不动对端已有数据
3. **行业 enum 校验**:不在白名单提示继续/取消
4. **模糊匹配**:多个候选时列出 top 3,严禁写错客户
5. **新建不去重**:靠写入时间戳 + 后续 `dedup.py` 清理

## 后端状态

| 后端 | 路径 | 状态 |
|---|---|---|
| Obsidian vault md | `$VAULT/11_customer/客户资料/` | ✅ 唯一活源 |
| WPS Excel | `~/Documents/WPS/workplace/My customer _客户数据表.xlsx` | ⏳ 由 customer-manager 推回 |
