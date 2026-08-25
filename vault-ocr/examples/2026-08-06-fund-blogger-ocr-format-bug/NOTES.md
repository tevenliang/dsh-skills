---
title: "案例：百炼 VL 表格格式输出不一致 → 事后修复"
date: 2026-08-07
vault_source: "subscription/xiaohongshu/每日养基实录/2026-08-06_8.6基金大佬[向右R]操作简报.md"
images_count: 5
model: qwen3-vl-plus
status: 已修复
commits:
  - "vault a0ea996: 初次 OCR 回填"
  - "vault 6eeae0f: 修复渲染异常"
  - "skill 5b69016: 强化 prompt + fallback"
---

# 案例：百炼 VL 表格格式输出不一致 → 事后修复

## 背景

2026-08-06 用户在 Obsidian 中触发 vault-ocr，对一篇 5 张图的小红书博客做 OCR。
- 模型：阿里云百炼 `qwen3-vl-plus`
- 工具：`bl vision describe --output json` × 5（5 张图全部成功，无 API 错误）
- 脚本：`vault-ocr/scripts/append_results.py`

5/5 图片 OCR 文本完整识别，但 Markdown 渲染时 **4/5 区块异常**。

## 问题分布

| 图片 | 模型原始输出片段 | 渲染问题 | 严重度 |
|------|----------------|---------|--------|
| 1 | `Info Doc. Recyclable / 8.6 / 🐮基金大佬 / 👉操作简报` | ✅ 封面，无表格 | OK |
| 2 | `8月6日 博主操作汇总\n\|...\|` | 标题缺 `#` → 显示为普通段落 | 🟡 中 |
| 3 | `# 8月6日 博主操作汇总\n\n\|...\|` | ✅ **唯一完全正确** | OK |
| 4 | ```` ```markdown\n\|...\|\n``` ```` | **整张表格被代码块包裹，完全不渲染** | 🔴 严重 |
| 5 | `8月6日 模块操作汇总\n\|...\|` | 标题缺 `#` → 显示为普通段落 | 🟡 中 |

**关键观察**：同样的 prompt、同样的模型、同一篇博客 5 张图 → 5 种输出风格不一致。
说明 VL 模型对 prompt 里的"格式约束"遵从度不保证100%，需要设计 **事后修复 fallback**。

## 修复方案（不重跑 bl）

不需要重新调用 `bl vision describe`（避免额外计费 + 同样的问题可能再出现）。
直接用 Python 编辑 OCR 区块：

```python
# fix_ocr_section.py —— 处理单张图的 OCR 区块
from pathlib import Path

p = Path("<vault-path>/article.md")
text = p.read_text(encoding='utf-8')

fixes = []

# 修复 1: 标题缺 # (匹配 "### 图片 N" 后第一行非 # 开头的短行)
import re
def fix_missing_h1(match):
    section = match.group(0)
    lines = section.split('\n')
    # lines[0] = "### 图片 N", lines[1] = "" (空行), lines[2] = 标题
    if len(lines) >= 3 and not lines[2].startswith('#'):
        # 启发式: 标题行长度 < 30 且包含中文 / 数字
        if 4 <= len(lines[2]) <= 30 and any('\u4e00' <= c <= '\u9fff' for c in lines[2]):
            lines[2] = '# ' + lines[2]
            fixes.append(f"  + 图片区块 H1 标题补全: {lines[2]}")
    return '\n'.join(lines)

text = re.sub(r'### 图片 \d+\n\n.*?(?=\n### 图片|\Z)', fix_missing_h1, text, flags=re.DOTALL)

# 修复 2: 去掉 OCR 区块内 ```markdown 和 ``` 包裹
text = re.sub(r'(### 图[^\n]+\n\n)```markdown\n', r'\1', text)
text = re.sub(r'(```\n)(### 图)', r'\2', text)

p.write_text(text, encoding='utf-8')
print('\n'.join(fixes) if fixes else '无需修改')
```

## 修复后验证

| 验证项 | 命令 | 期望 |
|--------|------|------|
| OCR 子标题数 = 图片数 | `grep -c '^### 图片' article.md` | 5 |
| 无残留 ``` 包裹 | `grep '^```' article.md` | 空输出 |
| 表格语法正确 | `awk '/^\|.*\|$/{count++} END{print count}'` | ≥ 30 行 |

## 经验沉淀

1. **prompt 强化不够**：VL 模型对"用 # 输出标题"等格式指令遵从度低，prompt 写再多规则也只解决概率问题
2. **必须设计 fallback**：OCR 流水线本质上是"模型输出 + 后处理"，后处理必须包含格式纠错
3. **修复成本低**：单文件 5 张图修复 < 1 秒，无需重新调用 API，省钱省时
4. **不要把"模型正确"当默认假设**：每个 OCR 区块都要 grep 检查一次

## 相关 commits

- `vault a0ea996` — vault 初次 OCR 回填（含问题版本）
- `vault 6eeae0f` — vault 修复渲染异常（标题加 # + 去 ``` 包裹）
- `skill 5b69016` — vault-ocr SKILL.md 强化 prompt + fallback 段落
