# 后台 Agent Prompt 模板

> 用于批量蒸馏某个一级目录下所有二级目录。
> 从 `vault-batch-distiller` 迁移过来（v8 整合）。

## 输入

- 一级目录路径：`/Users/tianwenliang/Documents/steven_vault/{L1}`
- 输出目录：`/Users/tianwenliang/Documents/steven_vault/llmwiki/{L1}`
- 二级目录列表（由主 agent 提供）

## 处理顺序

按二级目录逐个处理。

## 每个二级目录流程

1. 用 `extract_md.py` 提取该目录下所有 md 的标题层级 + 开头摘要：
   ```bash
   python3 scripts/extract_md.py \
     --dir "/Users/tianwenliang/Documents/steven_vault/{L1}/{L2}" \
     --out /tmp/{L2}_extract.json
   ```
2. 读取提取结果，基于摘要做分类蒸馏。
3. 生成研究笔记到 `llmwiki/{L1}/{L2}-YYYY-MM-DD.md`。
4. 校验死链：
   ```bash
   python3 scripts/validate_links.py \
     --note "/Users/tianwenliang/Documents/steven_vault/llmwiki/{L1}/{L2}-YYYY-MM-DD.md" \
     --src "/Users/tianwenliang/Documents/steven_vault/{L1}/{L2}"
   ```
5. 修复死链直到 0。
6. 在 `llmwiki/{L1}/.__progress.md` 追加完成记录。

## 笔记结构

```markdown
# {L2}主题研究笔记

## 提炼总览
- 总文件数：X / 总字符数：Y / 总标题数：Z
- 核心共识：...
- 关键分歧/张力：...

## Action Items
- ...

## 分类蒸馏
### A. {分类名}
1. **[[文件名]]**：一句话核心观点
   - 来源：[[文件名]]
   - 证据：🟢/🟡/🔴
   - 原文要点：...

### B. ...

## 收件筐 / 偏离或空内容
## 跨主题洞察
## 矛盾与存疑
## 关键词索引
```

## 分片规则

单个二级目录 md 数量 > 30 时，分片每批 ≤30，先生成子摘要，再综合。

## 双向链接

所有来源写成 `[[文件名]]`（去掉 `.md`），必须 0 死链。注意文件名中的空格、全角符号、`[` `]`、emoji 等都要精确匹配。

## 完成汇报

列出：成功文件清单、失败/跳过原因、耗时、阻塞。

## 上传到乐享（可选，v8 新增）

如果用户希望把生成的 wiki 笔记分发到乐享知识库，按 vault-wiki SKILL.md 的 Step 5 执行：

```bash
python3 scripts/upload_to_lexiang.py \
  --vault "$VAULT" \
  --note "$VAULT/llmwiki/{L1}/{L2}-YYYY-MM-DD.md" \
  --l1 "{L1}"
```

成功的话 wiki frontmatter 会自动添加 `lexiang_url` 字段；失败则添加 `lexiang_status: waf_blocked/empty/error`。
