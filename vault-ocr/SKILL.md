---
name: vault-ocr
description: 对指定 Obsidian Vault Markdown 文章中的图片执行
  OCR，并把识别结果按图片顺序插入原文件下方。用户指定一篇文章、要求识别图片、图片转文字、OCR
  回填、或说“把图片内容写回源文件”时使用；默认使用阿里云百炼 `bl vision describe`，适用于 PNG/JPG 等本地图片嵌入的 `.md`
  文件。
disable-model-invocation: true
---

# Vault OCR

对 Vault 中“正文主要由图片组成”的 Markdown 文章做批量图片识别，并把结果回填到同一源文件。保留原图片链接，不覆盖原文；OCR 结果追加在文件末尾（即图片区块下方）。

## 执行流程

### 1. 定位并检查源文件

- 将用户给出的相对路径解析到 `/Users/tianwenliang/Documents/steven_vault/`；用户给出绝对路径时直接使用。
- 先读取源 Markdown，提取所有图片嵌入，支持：
  - Obsidian wikilink：`![[media/x.png]]`
  - Markdown 图片：`![alt](media/x.png)`
- 相对图片路径优先相对于源文件所在目录解析；若不存在，再相对于 Vault 根目录解析。不要修改或搬移图片。
- 若找不到图片，停止并报告缺失路径；不要凭空生成 OCR 正文。
- 若源文件已经有 `## 图片识别结果（百炼 OCR）`，默认停止，避免重复写入；用户明确要求重做时才替换已有 OCR 区块。

### 2. 调用百炼视觉模型

这是用户明确指定的 Bailian OCR 工作流，直接使用 `bl`，不要改用普通文本模型。

首次运行 `bl` 前：

1. 读取 `/Users/tianwenliang/.agents/skills/bailian-protocol/SKILL.md`。
2. 按该协议完成版本预检；若 skill 版本与 CLI 不一致，先同步 skill，不要猜参数。
3. 阅读 `/Users/tianwenliang/.agents/skills/bailian-gen/reference/vision.md`，确认命令参数。

对每张本地图片各执行一次：

```bash
bl vision describe \
  --image "/absolute/path/to/image.png" \
  --model qwen3-vl-plus \
  --prompt '请对这张图片进行高精度OCR。

格式约束（强制）：
- 逐字提取所有可见中文、英文、数字和符号，保持原有分组与顺序
- 表格直接输出 Markdown 表格语法（| ... |），不要用 ```markdown ... ``` 代码块包裹
- 图片如有独立标题行（如"8月6日 博主操作汇总"），请用 `# 标题` 一级标题语法输出
- 不要总结，不要补写看不清的内容；看不清处标记为【无法辨认】
- 只输出 OCR 正文，不要任何前言或解释'  \
  --output json
```

- 本地路径直接传给 `--image`；不要手动上传 OSS。
- 图片较多时可并行调用，但控制并发，遇到限流则串行重试。
- 将每次 JSON 原样临时保存，成功后从 `choices[0].message.content` 取正文。
- OCR 结果是视觉语言模型输出，不是保证逐字准确的专用 OCR 引擎；回填前对照原图检查基金名、博主名、数字、百分比、加减号和单位。
- 看不清的内容保留 `【无法辨认】`，不要猜测。
- **格式一致性 fallback**：即使 prompt 强化过，模型仍可能偶尔不遵守（如漏写 `#` 标题、或把表格误识别为 markdown 代码块）。回填后用以下命令快速检测并修复：
  ```bash
  # 检测 1: OCR 区块内是否被 ```markdown ... ``` 误包裹
  grep -nE '^\`\`\`(markdown)?$' "<vault-path>/article.md"
  # 检测 2: OCR 子标题后下一行是否为独立标题（缺 #）
  awk '/^### 图片/{getline next_line; if (next_line ~ /^[0-9#月日]|博主|模块/ && next_line ! ! /^#/) print NR": "$0" → "$next_line}' "<vault-path>/article.md"
  ```
  命中后用 sed/python 修正（去掉首尾 ``` ；标题行首加 `# `），不要重新调用 `bl vision describe`。

### 3. 组装并回填

在原文件所有图片嵌入之后追加：

```markdown
## 图片识别结果（百炼 OCR）

> 识别模型：阿里云百炼 `qwen3-vl-plus`。以下内容按图片顺序转写；仅为公开信息整理，不构成投资建议。

### 图片 1

[图片 1 OCR 正文]

### 图片 2

[图片 2 OCR 正文]
```

推荐使用内置脚本将 `bl` 的 JSON 结果安全写回：

```bash
python3 /Users/tianwenliang/.agents/skills/vault-ocr/scripts/append_results.py \
  "/absolute/path/to/article.md" \
  /tmp/ocr-1.json /tmp/ocr-2.json \
  --model qwen3-vl-plus
```

已有 OCR 区块且用户明确要求重做时：

```bash
python3 /Users/tianwenliang/.agents/skills/vault-ocr/scripts/append_results.py \
  "/absolute/path/to/article.md" \
  /tmp/ocr-1.json /tmp/ocr-2.json \
  --model qwen3-vl-plus \
  --replace-existing
```

### 4. 验证和提交

- 确认图片链接仍完整存在，OCR 区块只出现一次，且图片顺序与识别结果顺序一致。
- 检查 Markdown 表格列数、代码块闭合、中文编码和文件可读性。
- **格式校验**：`grep -c '^### 图片' article.md` 应等于图片总数；OCR 区块内不应残留 ``` 代码块包裹。
- 向用户说明实际使用的模型、识别张数、是否做了人工校对以及任何低置信度字段。
- 改动完成后立即提交源 Vault 文件；只提交本次目标文件，不要把其他工作区改动带入 commit。

## 额度与错误说明

- `qwen3-vl-plus` 的 RPM（每分钟请求数）和 TPM（每分钟 token 处理量）属于速率限制，使用 `bl quota list --model qwen3-vl-plus --output json` 查询。
- 免费额度余额使用 `bl usage free --model qwen3-vl-plus --output json` 查询；若返回 `BailianGateway.Team.NotAuthorised`，如实报告“当前无法读取余额”，不要把它误报为模型不可用。
- `bl vision describe` 成功返回并不等同于免费额度余额可查；不要向用户保证“还有多少免费次数”。

## 参考案例

实际生产中百炼 VL 模型的输出格式可能不一致（同一篇博客 5 张图，4/5 渲染异常）。完整案例 + 事后修复脚本见：

- `examples/2026-08-06-fund-blogger-ocr-format-bug/NOTES.md` — 问题诊断 + 修复方案 + 验证清单
- `examples/2026-08-06-fund-blogger-ocr-format-bug/fix_ocr_section.py` — 可直接 `python3 fix_ocr_section.py <vault-path>/article.md` 调用的修复脚本

**已知限制**：
- 修复脚本启发式判断"是否为标题行"，对 >30 字符的长文本不触发（保守策略）
- 文档末尾孤立的 ``` 残留不会自动清除（要求 ``` 后必须跟 ### 图才处理）
- 修复后务必 Obsidian 实际肉眼校验一次，启发式可能误伤
