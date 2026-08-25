---
name: wechat-invoice
description: 整理 macOS 微信缓存目录中的电子发票 PDF（dzfp_*），直接读取源文件（零拷贝），按 (公司, 月份) 生成开票记录
  Excel，状态由 manifest.json 持久化。Use this skill when the user asks to
  处理微信附件中的发票、整理开票记录、生成开票 Excel、从 dzfp 提取字段 等场景。Trigger phrases include
  "微信发票"、"开票记录"、"dzfp"、"电子发票"、"开票 Excel"。
agent_created: true
disable-model-invocation: true
---

# Wechat Invoice

## Purpose

把微信缓存目录（`~/Library/Containers/com.tencent.xinWeChat/.../msg/file/YYYY-MM/`）里的电子发票 PDF（`dzfp_*.pdf`）直接解析，按"公司 × 月份"整理成 Excel 开票记录：**不拷贝任何源文件**，只读源文件并把结果写入 manifest + Excel。

适用于：
- 财务/会计/月度对账场景
- 多个公司需要分别出开票台账
- 微信自动给重复下载的文件加 `(1)`、`(2)` 后缀造成混乱

## Design

### 目录结构（项目目录）

```
project/
├── manifest.json           ← 处理状态持久化（MD5 → 发票字段）
└── 开票记录/               ← 唯一产出（一个公司一个 xlsx）
    ├── 启智路演中.xlsx
    └── 跨维智能数字.xlsx
```

**不再需要**：`raw/`、`invoices/`、`_skipped/`（旧项目可安全删除）

### manifest.json 结构

```json
{
  "source_base": "/path/to/wechat/file/",
  "companies": [{"key": "...", "match": "..."}],
  "processed": {
    "<md5_hash>": {
      "filename": "dzfp_xxx.pdf",
      "month": "2026-07",
      "status": "ok|skipped|error",
      "invoice": { "购买方": "...", "发票号码": "...", ... }
    }
  }
}
```

### 工作流程

```
1. 扫描 source_base/YYYY-MM/ 下所有 dzfp_*.pdf，计算 MD5
2. 查 manifest：
   ├── 已处理 + MD5 匹配 → 复用缓存
   ├── MD5 不匹配（文件变了）→ 重新解析
   └── 未处理 → 新增，解析 PDF
3. 发票号去重：同一张发票在不同月份出现时只保留一条
4. 按 (公司, 月份) 汇总，写 Excel
```

### 增量支持

- manifest.json 存在时自动增量：只处理新增/变更的 PDF
- `--reparse` 可强制重新解析所有发票（忽略缓存）

## When to Use

触发条件（满足任一即应启用本 skill）：
- 用户提到「微信发票」「微信附件」「开票记录」「开票 Excel」
- 出现 `dzfp_` 命名的 PDF 文件
- 需要按公司+月份整理发票

## Workflow

### Step 1 — 确认源目录与目标公司

向用户确认：
1. **微信源根目录**：默认 `~/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/<wxid>/msg/file/`
2. **要整理的月份**：建议近 3~4 个月
3. **目标公司列表**：

```json
"companies": [
  {"key": "启智路演中", "match": "启智路演中"},
  {"key": "跨维智能数字", "match": "跨维（深圳）智能数字"}
]
```

### Step 2 — 建项目目录并写入 config.json

```bash
mkdir -p <project>/开票记录
```

config.json 格式：

```json
{
  "project": "/abs/path/to/project",
  "source": {
    "base": "/abs/path/to/wechat/.../file",
    "months": ["2026-04", "2026-05", "2026-06", "2026-07"]
  },
  "records_subdir": "开票记录",
  "companies": [
    {"key": "启智路演中", "match": "启智路演中"},
    {"key": "跨维智能数字", "match": "跨维（深圳）智能数字"}
  ]
}
```

### Step 3 — 一键运行

```bash
PY=/Users/tianwenliang/.codex/binaries/python/versions/3.13.12/bin/python3

# 一键：扫描源文件 → 解析 → 生成 Excel
$PY scripts/ingest.py --config config.json

# 增量（只处理新增/变更的 PDF）
$PY scripts/ingest.py --config config.json

# 强制重新解析所有发票
$PY scripts/ingest.py --config config.json --reparse

# 干跑（只看不写）
$PY scripts/ingest.py --config config.json --dry-run
```

### Step 4 — 校验

打开每个 Excel 确认：
- 汇总 sheet「月份」列带超链接，可跳到对应月份 sheet
- 月份 sheet 末行有合计 SUM 公式
- 发票号去重后数量与预期一致

## Scripts 说明

| 脚本 | 职责 |
|------|------|
| `ingest.py` | 主入口：扫描源文件、更新 manifest、调用 build_excel |
| `manifest.py` | MD5 状态管理、增量解析决策 |
| `parse_invoices.py` | 解析单个 dzfp PDF，提取字段 |
| `build_excel.py` | 按公司生成 Excel（汇总 + 月份 sheet） |

## 依赖

- Python 3.13+：`pdfplumber`、`openpyxl`
- 安装：`/Users/tianwenliang/.codex/binaries/python/versions/3.13.12/bin/python3 -m pip install pdfplumber openpyxl -q`

## 已知坑

1. **餐饮普通发票**：数量/单价列在 PDF 中被压窄为空，解析器自动降级处理，不影响金额统计。
2. **项目名跨行**：`信息技术服务` 在 PDF 中被拆成两行，解析器做续行拼接。
3. **微信 `(1)` `(2)` 后缀**：按 **MD5 哈希** 判定真重复，自动去重。
4. **加密 PDF**：返回 `{"错误": ...}` 占位记录，跳过处理。

## 迁移旧项目

旧项目已有 `raw/`/`invoices/`？直接运行新脚本，首次会自动生成 `manifest.json`，之后可删除 `raw/` 和 `invoices/` 目录节省空间。
