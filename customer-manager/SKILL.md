---
name: customer-manager
description: 客户资料统一管理中心(由 customer-search / customer-update / customer-record /
  customer-vault 合并而来)。云端 Excel 为唯一真源,vault 为只读衍生品。五大能力:① 只读查询客户(查/列/筛) ②
  写入外部工商信息字段 ③ 记录销售跟进内部字段 ④ Excel→vault 单向同步 ⑤ vault frontmatter 规范化。所有脚本在
  scripts/ 同目录自包含,无跨 skill 的 sys.path 依赖。触发词:"查客户 X"/"X 在吗"/"新建客户 X"/"更新客户
  X"/"记录:今天和 X 通了电话"/"X 下一步计划是下周一"/"把 X 写进 vault"/"vault 同步"/"vault
  跑批"/"列出所有客户"/"我有多少个 X 行业客户"。
version: 3
author: Steven Liang
platforms:
  - macos
changelog:
  - 3.2 (2026-08-16): search.py cascade 新增企查查 CLI (qcc),调通 agent.qcc.com API Key(已存
      vault 账号密码);外部查询升级为 5 级:企查查→天眼查→水滴→天机商查;企查查 MCP 已在 Codex 禁用,使用本地 CLI 替代。
  - 3.2 (2026-08-16): search.py cascade 新增企查查 CLI (qcc),调通 agent.qcc.com API Key(已存
      vault 账号密码);外部查询升级为 5 级:企查查→天眼查→水滴→天机商查;企查查 MCP 已在 Codex 禁用,使用本地 CLI 替代。
  - 3.1 (2026-08-16): search.py 新增 `--cascade` 外部级联查询:Excel 命中 0 行时自动触发天眼查 CLI →
      天机商查兜底;数据源优先级文档更新;企查查 MCP 因无本地 auth 跳步。
  - 3.0 (2026-08-10): 合并 customer-search / customer-update / customer-record /
      customer-vault 为单一 skill。scripts/ 内联全部 10 个模块,消除跨 skill 的 sys.path.insert
      脆弱依赖;field_defs 改为从 shared_map 单一派生(真源收敛);缓存目录更名为 customer-manager。4 个旧
      skill 归档至 ~/.agents/archived_skills/。
  - 2.x (2026-08-07): 四个独立 skill 各自演进(见各自历史 SKILL.md,已归档)。
disable-model-invocation: true
---

# customer-manager — 客户资料统一管理中心

> **数据真源单一**:云端 Excel (`My customer _客户数据表.xlsx`) 是唯一准确数据源。vault 只是只读衍生品,绝不回写 Excel。
> **角色不强制分离**:日常你常常「先查 → 再写」连着来(例如刚查了"路演中",接着把信息录入客户表)。本 skill 五个能力可自由组合调用,不需要先切换"角色"。

## 五个能力 & 路由

| 能力 | 入口脚本 | 干什么 | 写不写盘 |
|---|---|---|---|
| **查询** | `scripts/search.py` | 在 Excel 里搜客户名 → 命中返回 22 字段;未命中用 `--cascade` 触发天眼查→天机商查外部兜底 | 纯只读,绝不写 |
| **录入外部信息** | `scripts/update.py` | 把工商/简介/产品/财务/网络搜索结果写入 Excel 外部字段(新增或 upsert) | 直接写 Excel |
| **记录销售跟进** | `scripts/record.py` | 写客户记录/下一步行动/下一步计划/联系人等销售内部字段 | 直接写 Excel |
| **同步 vault** | `scripts/sync.py` | 读 Excel → 单向写 vault md(`11_customer/客户资料/`) | 直接写 vault |
| **vault 规范化** | `scripts/sanitize_vault.py` | frontmatter 强单引号化 + 备注迁出 frontmatter + 清理 markdown 逃逸 | 直接写 vault |

**判断调用哪个**(按你的意图,不是按"角色")：

- "查客户 路演中" / "X 在吗" / "列出所有互联网客户" / "我有多少个机会阶段客户" → **search.py**
- "新建客户 无锡村田" / "更新客户 路演中" / 你贴一段工商搜索结果让我录入 → **update.py**
- "记录:今天和 X 通了电话" / "X 下一步计划是下周一" / "加联系人 张三 138..." → **record.py**
- "把路演中写进 vault" / "vault 同步" / "vault 跑批" → **sync.py**
- "整理 vault" / "规范化 frontmatter" → **sanitize_vault.py**

> 同一次对话里可以先 `search` 确认客户存在,再 `update`/`record` 补信息,最后 `sync` 推到 vault——顺序随意。

## 22 字段模型(单一真源 = `scripts/shared_map.py`)

`scripts/shared_map.py::FIELD_DEFS` 是 22 字段的**唯一真源**(Excel 列号 / 表头 / vault frontmatter key / 是否多行)。`scripts/field_defs.py` 从它派生(查表 + 单值/多行分类),杜绝两份定义分叉。

```
col  1 客户名称   | col  2 行业        | col  3 销售阶段  | col  4 客户标签
col  5 联系人     | col  6 客户记录    | col  7 文件链接  | col  8 下一步计划
col  9 下一步行动 | col 10 总结        | col 11 公司简介  | col 12 产品服务
col 13 财务状况   | col 14 下游        | col 15 营收      | col 16 人数
col 17 网站       | col 18 地址        | col 19 竞争对手  | col 20 城市
col 21 备注       | col 22 更新日期
```

**注意**:Excel 表头名 ≠ vault frontmatter key(部分字段)。例:col 6 Excel 叫"客户记录",vault 叫"跟进记录";col 7 Excel 叫"文件链接",vault 叫"关联文档";col 14 Excel 叫"下游",vault 叫"客户群体"。一切映射以 `shared_map.FIELD_DEFS` 为准。

### 字段分类(由 shared_map is_multiline 派生)

- **单值(覆盖)**:客户名称 / 行业 / 销售阶段 / 客户标签 / 下一步计划 / 下一步行动 / 营收 / 人数 / 网站 / 地址 / 竞争对手 / 城市 / 更新日期
- **多行(可追加)**:联系人 / 客户记录 / 文件链接 / 总结 / 公司简介 / 产品服务 / 财务状况 / 下游 / 备注

## 数据源优先级

1. **云端 Excel** → 主数据源(查询/写入都以它为基准)
2. **用户输入** → 写入时最高优先级(你最清楚)
3. **外部工商查询(级联)** → Excel 查询 0 命中时按序自动兜底:
   - Stage 1: 企查查 CLI(qcc) (`tyc company registration-info`)
   - Stage 2: 天眼查 CLI(tyc)
   Stage 3: 水滴信用 MCP(shuidi-data)
   Stage 4: 天机商查 (`tianji-search/business_query.py`,元宝搜索兜底)
   - 
4. **水滴 MCP**(`shuidi-data`)→ 结构化工商数据(21 工具),录入外部字段时主用
5. **元宝搜索**(`tencent-yuanbao-search`)→ 录入的业务方向认知

## 关键写入约定

### upsert 守卫(search/update)
- 源端字段有内容 → 覆盖对端
- 源端字段空 → **保留**对端已有值(不破坏)
- 例外:`更新日期` 永远刷成今天

### 自动 sanitize(update)
- 多行字段 `"- "` 列表前缀 → 自动转 `"• "`,绕开 kdocs-cli 写入 `"- "` 开头内容时返回 `result:ok` 却静默失败的 bug
- 字段值里嵌入的 markdown 表格/标题/加粗 → 清理(避免 vault frontmatter 逃逸);**备注**字段例外(它是调研报告归集处,可保留 markdown)

### 下一步计划 vs 下一步行动(record 内置 LLM 推理)
- 含明确**日期**(下周一/2026-08-15/明天…)→ 写 **col 7 下一步计划**
- 只描述**事情**没日期 → 写 **col 8 下一步行动**
- 描述发生过的事 → 写 **col 5 客户记录**(mmdd 前缀)

### vault 单向同步(sync)
- Excel → vault 单向;vault 改完**不**回写 Excel,**不**做冲突对比
- 备注字段不进 frontmatter,落到正文 `## 7. 备注` 段(用 `>` 引用块包裹)
- 多行字段用 `|` 块标量 / 列表字段用 YAML list,避免 PyYAML 解析失败

## 依赖

- WPS MCP(`kdocs-cli`)— 读/写云端 Excel
- `tencent-yuanbao-search` skill — 查询兜底 + 录入认知
- `shuidi-data` MCP(可选)— 录入外部字段的结构化工商数据
- 云端 file_id:`s5p5NuXrK1MrLbEGE6jurxDp2np4wYpvL`
- 云端分享链接:`https://www.kdocs.cn/l/cgoYxmCqc8Ol`
- vault 路径:`~/Documents/steven_vault/11_customer/客户资料/{客户名称}.md`

## 不做什么(NEVER,除非你明确要)

- ❌ 查询能力绝不写任何东西(不写 Excel / 不写 vault)
- ❌ vault → Excel 回写(单向,不允许)
- ❌ 删 vault 文件 / 同步 mtime 到 vault
- ❌ 批量录入(一次一个客户)
- ❌ 失败缓存(直接报错,不静默)

## 各能力详细用法

### 1. search.py(只读查询)

```bash
python3 scripts/search.py 路演中                 # 模糊搜单个客户
python3 scripts/search.py 路演中 --verbose       # 输出完整原文(便于复制)
python3 scripts/search.py --list                 # 列出所有客户
python3 scripts/search.py --list --industry 互联网
python3 scripts/search.py --list --stage 机会
python3 scripts/search.py --refresh --list       # 强制刷新缓存
python3 scripts/search.py --cascade 路演中       # 外部级联查询:天眼查→天机商查
python3 scripts/search.py --cascade 新客户名      # Excel 0命中时触发外部查询
```

- 缓存:`~/.cache/customer-manager/excel_cache.json`,按云端 mtime/version 失效,默认 TTL 10 分钟
- 命中 0 行 → 提示用元宝兜底,并问"要不要新增到 Excel?"
- 命中多行 → 列出全部,让你选

### 2. update.py(录入外部信息)

```bash
python3 scripts/update.py '<22 字段 JSON>'       # 直接写
python3 scripts/update.py --stdin                # 从 stdin 读 JSON
python3 scripts/update.py --dry-run '<JSON>'     # 只预览
```

JSON 字段名 = `field_defs.EXCEL_FIELDS` 表头;`客户名称` 必填。命中→upsert 守卫覆盖;未命中→append 新行。

### 3. record.py(记录销售跟进)

```bash
python3 scripts/record.py '<JSON>'
python3 scripts/record.py --stdin
```

JSON:
```json
{"customer_name":"深圳市路演中网络科技有限公司",
 "writes":{"客户记录":"通了电话,聊了合同细节","下一步行动":"联系陈滢发合同","下一步计划":"2026-08-10","联系人":"李四 13800000001"}}
```
客户记录/联系人追加(mmdd 前缀),下一步计划/行动/更新日期覆盖。

### 4. sync.py(Excel→vault 单向)

```bash
python3 scripts/sync.py '路演中'                # 单客户
python3 scripts/sync.py --all                   # 全部
python3 scripts/sync.py --all --industry 互联网  # 按行业
python3 scripts/sync.py --all --dry-run         # 只预览
```

### 5. sanitize_vault.py(vault 规范化)

```bash
python3 scripts/sanitize_vault.py --dry-run     # 扫描+报告,不动盘
python3 scripts/sanitize_vault.py --apply       # 写盘(先自动 git 备份)
python3 scripts/sanitize_vault.py --apply --only 路演中
```

## 实现状态

**v3.0(2026-08-10)代码全部就绪并通过测试**:

| 文件 | 状态 |
|---|---|
| `scripts/shared_map.py` | ✅ 22 字段唯一真源(迁移自 customer-vault) |
| `scripts/field_defs.py` | ✅ 从 shared_map 派生(分类断言通过) |
| `scripts/kdocs_client.py` | ✅ kdocs-cli 封装(**v3.1 修日期读取**:日期单元格取 `understandableType.value` 而非序列号) |
| `scripts/cache.py` | ✅ 缓存(目录更名 customer-manager) |
| `scripts/formatter.py` | ✅ 输出格式化(原样) |
| `scripts/search.py` | ✅ 查询(原样) |
| `scripts/update.py` | ✅ 外部字段录入(修 import) |
| `scripts/record.py` | ✅ 销售跟进(修 import) |
| `scripts/sync.py` | ✅ Excel→vault 单向(修 import) |
| `scripts/sanitize_vault.py` | ✅ vault 规范化(修 import) |
| `tests/test_sync_yaml.py` | ✅ 6/6 通过(含 307 真实档案回归) |

历史参考:`references/SKILL_v1.0_vault-writer.md`(customer-update v1.0 写 vault 版本文档)。
