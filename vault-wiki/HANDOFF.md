---
title: Handoff - VM 端批量蒸馏任务
type: handoff
status: active
created: 2026-09-03
tags:
  - handoff
  - vault-wiki
  - 蒸馏
  - 乐享
source: 由 Mac (DSH agent) 移交到 VM (DSH agent)
---

# Handoff: VM 端继续做 vault 批量蒸馏

> 闻哥(Steven Liang)说:**"你写一个 handoff 文档吧,我让 VM 继续做蒸馏的事情"**
>
> 本文是给 VM 端 DSH agent 看的任务交接单,你在 VM 端接着干。

---

## TL;DR

继续把 `/home/ubuntu/webdav/steven_vault/` 下还没蒸馏的 L1 目录跑完 `vault-wiki` v8 的 `batch-distill` 模式,然后用 `upload_to_lexiang.py` 把每篇 wiki 上传到乐享知识库。

**全部使用 vault-wiki v8**(已推到 VM,见后文)。

---

## 0. 上下文(给 VM agent 看的 30 秒版)

我是 Mac 上的 DSH agent,今天刚把 `~/.dsh/skills/vault-wiki` 升级到 **v8**,关键变化:

| 变化 | 含义 |
|:--|:--|
| 吞并 `vault-batch-distiller` | 不要再调用那个 skill,全部用 `vault-wiki` |
| 新增 **Step 5 乐享上传** | 蒸馏完立刻 `upload_to_lexiang.py` |
| 新增 `single-wiki` + `batch-distill` 两种模式 | 看清楚输入选模式 |
| 证据等级 🟢/🟡/🔴 | 每个核心观点打标签 |
| 0 死链强制校验 | 用 `validate_links.py` 验完才完成 |

**Mac 上已完成**:
- `21_ai/agent/` 已蒸馏为 `AI-Agent知识库（蒸馏版）.md`(60KB)并已上传到乐享
- 失败 2 个 WAF 拦截 + 1 个空文件,已标记

**VM 上要做的**:跑剩下没蒸馏的 L1 目录。

---

## 1. 环境清单(已就绪)

```bash
# Vault 根目录
VAULT=/home/ubuntu/webdav/steven_vault

# vault-wiki v8 已在
SKILL=~/.dsh/skills/vault-wiki/
ls $SKILL/{SKILL.md,scripts/upload_to_lexiang.py,references/lexiang-setup.md,references/prompt-template.md}

# 乐享 MCP 已配
cat ~/.dsh/profiles/web/cordis.patch.yml | grep -A 12 lexiang
# 验证:whoami 返回 "梁生" / "梁生的组织" / space=d8d906983d6e4ffbbc5b53edde5f0086

# python3
python3 --version  # Python 3.12.3
```

**已存在的产物**(别覆盖):
- `llmwiki/` 目录有 2026-08-17 旧版(老 `vault-batch-distiller` 输出)
- `uploaded/lexiang_uploads.json` 有 Mac 上传 2 条记录(蒸馏版 + 测试文件夹)

---

## 2. 任务清单

按优先级跑(闻哥的需求强度):

| 优先级 | L1 目录 | 文件数估 | 备注 |
|:--|:--|:--|:--|
| P0 | `21_ai/agent/` | 93 | **已完成**,跳过 |
| P1 | `21_ai/claude/` | ~? | AI 编程相关,与已有重叠高 |
| P1 | `21_ai/codex/` | ~? | 同上 |
| P1 | `21_ai/openclaw/` | ~? | OpenClaw 专题 |
| P1 | `21_ai/hermes/` | ~? | Hermes 专题 |
| P1 | `21_ai/coding/` | ~? | 编程 |
| P1 | `21_ai/cli/` | ~? | 工具链 |
| P1 | `21_ai/llm/` | ~? | 模型 |
| P1 | `21_ai/prompt/` | ~? | 提示词 |
| P1 | `21_ai/skills/` | ~? | DSH skills |
| P1 | `21_ai/workbuddy/` | ~? | WorkBuddy |
| P1 | `21_ai/wiki归档/` | ~? | 旧归档 |
| P1 | `21_ai/知识库/` | ~? | 知识库类 |
| P2 | `13_资讯/` | ~? | 资讯类 |
| P2 | `22_应用工具/` | ~? | 工具 |
| P2 | `23_财富/` | ~? | 投资 |
| P2 | `12_产品方案/` | ~? | 产品 |
| P2 | `24_阅读思考/` | ~? | 阅读 |
| P2 | `25_职业/` | ~? | 职业 |
| P2 | `26_销售/` | ~? | 销售 |
| P2 | `31_家庭生活/` | ~? | 生活 |
| P3 | 剩下的 L1 | ~? | 看时间 |

**先扫描确定范围**:

```bash
cd $VAULT
for d in [0-9]*/; do
  cnt=$(find "$d" -name "*.md" -type f | wc -l)
  echo "$d: $cnt md"
done
```

跳过这些目录(产物):
- `llmwiki/`、`uploaded/`、`.trash/`、`WorkBuddy-知识框架/`

---

## 3. 每个 L1 目录的执行流程

```bash
cd $VAULT

# === 步骤 1:扫描 L1 下的 L2 目录 ===
L1="21_ai"  # 改成实际的
ls -la $L1/

# === 步骤 2:对每个 L2 跑 batch-distill ===
# 单目录 ≤ 30 md:一次跑完
python3 ~/.dsh/skills/vault-wiki/scripts/extract_md.py \
  --dir "$L1/claude" --out /tmp/claude_extract.json

# 然后用 DSH agent(就是你)读 extract + 源文 → 生成 wiki 到
# $VAULT/llmwiki/$L1/claude-$(date +%F).md
# 遵循 vault-wiki SKILL.md 的两步法 + batch 模式笔记结构

# === 步骤 3:0 死链校验 ===
python3 ~/.dsh/skills/vault-wiki/scripts/validate_links.py \
  --note "$VAULT/llmwiki/$L1/claude-2026-09-03.md" \
  --src "$VAULT/$L1/claude"
# 必须输出 "OK: 0 dead links" 才算完成

# === 步骤 4:追加 progress ===
echo "- [$(date '+%Y-%m-%d %H:%M')] 完成 claude (X md) → claude-2026-09-03.md" \
  >> $VAULT/llmwiki/$L1/.__progress.md

# === 步骤 5:上传乐享 ===
python3 ~/.dsh/skills/vault-wiki/scripts/upload_to_lexiang.py \
  --vault "$VAULT" \
  --note "$VAULT/llmwiki/$L1/claude-2026-09-03.md" \
  --l1 "21_ai_claude"
# 成功会写 lexiang_url 到 frontmatter,失败标 lexiang_status
```

**L2 目录 > 30 md 时**:分批跑(见 `references/prompt-template.md` 的"分片规则")。

---

## 4. 笔记结构(batch-distill 模式)

```markdown
# {L2 主题}研究笔记

## 提炼总览
- 总文件数:X / 总字符数:Y / 总标题数:Z
- 核心共识:...
- 关键分歧/张力:...

## Action Items
- 2-4 条可操作结论

## 分类蒸馏
### A. {分类}
1. **[[文件名]]**:一句话核心观点
   - 来源:[[文件名]]
   - 证据:🟢/🟡/🔴
   - 原文要点:2-4 条 bullets

## 收件筐 / 偏离或空内容
## 跨主题洞察
## 矛盾与存疑
## 关键词索引
```

**关键**:
- 每个核心观点**必须**打证据等级 🟢/🟡/🔴
- 0 死链是硬要求
- 不要原样复制,从多源提炼重组

---

## 5. 乐享上传的注意事项

**已经在 Mac 上**:
- `21_ai_agent` 文件夹已创建
- `AI-Agent知识库（蒸馏版）.md` 已上传,URL 见 `/home/ubuntu/webdav/steven_vault/uploaded/lexiang_uploads.json`

**VM 跑的时候**:
- 每个 L1 用 `--l1 "{L1}_{主题}"` 创建独立文件夹(避免撞名)
- 或统一用 `--l1 "21_ai"` 一个文件夹(看你喜好)
- WAF 拦截的文件不要重试,标记 `⚠️ 需手动上传`
- token 失效(401)时去 https://lexiangla.com/mcp 续期

**上传后**:
- frontmatter 自动加 `lexiang_url` 字段
- 失败加 `lexiang_status: waf_blocked/empty/error`
- 写回 `$VAULT/uploaded/lexiang_uploads.json`

---

## 6. 进度汇报

每完成一个 L2,在 `$VAULT/llmwiki/$L1/.__progress.md` 追加:
```markdown
- [2026-09-03 16:30] 完成 claude (X md) → claude-2026-09-03.md
  乐享 URL: https://lexiangla.com/pages/xxx?company_from=...
```

完成整个 L1 后,更新总索引 `$VAULT/llmwiki/!INDEX-$(date +%F).md`:
```markdown
# Vault 蒸馏总索引 (2026-09-03)

| L1 | L2 | 文件数 | 蒸馏笔记 | 乐享 URL |
|:--|:--|:--|:--|:--|
| 21_ai | agent | 93 | agent-2026-08-17.md | https://... |
| 21_ai | claude | X | claude-2026-09-03.md | https://... |
| ... | | | | |
```

---

## 7. 不要做的事

1. **不要**重新蒸馏 `21_ai/agent/`(已完成)
2. **不要**覆盖 `$VAULT/llmwiki/21_ai/agent-2026-08-17.md`(Mac 上还有更全的 `AI-Agent知识库（蒸馏版）.md` 在 21_ai/agent/ 根目录)
3. **不要**碰 `~/.dsh/profiles/web/cordis.patch.yml` 的 lexiang 配置(已 OK)
4. **不要**重试 WAF 失败的文件(浪费 token)
5. **不要**忘记 0 死链校验(否则 wiki 跳转坏)

---

## 8. 万一卡住

| 症状 | 处理 |
|:--|:--|
| 401 token 过期 | 引导用户到 https://lexiangla.com/mcp 续期 |
| WAF 拦截 | 跳过,标 `lexiang_status: waf_blocked`,继续下一篇 |
| vault-wiki 找不到了 | `ls ~/.dsh/skills/vault-wiki/`,确认 SKILL.md 存在 |
| 死链校验不过 | 修复 [[wikilink]] 直到 0 死链 |
| python3 报错 | VM 是 Python 3.12.3,Mac 是 3.14,代码兼容性注意 |
| 0 文件目录 | 跳过,在 progress 标 "SKIP: empty" |
| cordis HMR 没生效 | 看下 `~/.dsh/profiles/web/cordis.patch.yml.bak-*` 备份,必要时恢复 |

---

## 9. 最终汇报格式

跑完一个 L1 后(可以跑完几个再汇报),给闻哥发:

```
## [L1 目录] 蒸馏完成

- 完成 L2 目录:N 个
- 生成 wiki 笔记:N 篇
- 上传乐享:成功 N / 失败 N(WAF: X, empty: Y)
- 死链校验:全部 0 死链
- 耗时:X 分钟
- 阻塞/异常:无 / [具体说明]

[接下来打算处理哪个 L1?]
```

---

## 10. 参考资源

- `~/.dsh/skills/vault-wiki/SKILL.md` — 完整 skill 定义
- `~/.dsh/skills/vault-wiki/references/prompt-template.md` — 后台 agent prompt 模板
- `~/.dsh/skills/vault-wiki/references/lexiang-setup.md` — 乐享 MCP 配置说明
- `~/.dsh/skills/vault-wiki/scripts/upload_to_lexiang.py --help` — 上传脚本用法
- Mac 已蒸馏样本: `$VAULT/21_ai/agent/AI-Agent知识库（蒸馏版）.md`(看 batch-distill 风格)

---

**祝顺利。** 闻哥(Steven)在 Mac 上等你汇报。
