---
name: daily-review
description: >
  每日复盘 — 当日与 dsh 助手对话总结。直接从 dsh 自身会话记录 ~/.dsh/sessions/ 提取用户真实提问和助手回答，
  按主题归类 (不含注入式上下文: runtime context / system-reminder / 技能说明等)。

  触发条件: - 「每日复盘」「daily review」「今日总结」「今天做了什么」 - 「生成 daily review」「输出今日总结」
keywords:
  - 每日复盘
  - daily review
  - 今日总结
  - 今天做了什么
  - 每日回顾
  - 每日汇报
disable-model-invocation: true
---

# Daily Review

生成当日复盘，**总结文件只需 1 段**:

1. **📋 当日 dsh 对话总结** — 直接从 dsh 自身的会话记录 `~/.dsh/sessions/` 提取用户真实提问和助手回答，按主题归类。

完整活动流水落 `04_agent/conversation/YYYY-MM-DD.md` 给 LLM 自己看, 总结文件落 `03_daily/YYYY-MM-DD-summary.md` 给用户看.

## 输出文件

- `04_agent/conversation/YYYY-MM-DD.md` — 当日 dsh 完整对话流水 (供 LLM 摸排用)
- `03_daily/YYYY-MM-DD-summary.md` — 给用户的极简总结, 只有上面 1 段

## 数据源: dsh 自身会话记录 (不是 wb / codex)

dsh 的聊天记录在本机自己的会话目录:

```
~/.dsh/sessions/<workspace-key>/<session-id>/session.jsonl.zstd
```

- 每个会话一个 **zstd 压缩** 的 JSONL (`.zstd`, 并非明文 `.jsonl`, 需先解压)
- 每行一个事件, 关键 type:
  - `user/message`      → 用户消息 (`data.content[].text`, `source.kind=user`)
  - `assistant/message` → 助手消息 (`data.message.content[]` 中 `type=text` 的 text)
- `time` 为**毫秒时间戳** (UTC), 按目标日期转 CST 过滤
- 剔除注入式上下文 (runtime context / system-reminder / MNEMON 快照 / 技能说明等), 只留真实对话

## 工作流程

### 第 1 步: 提取当日对话流水

```bash
python3 /home/ubuntu/.dsh/skills/daily-review/scripts/extract_today_msgs.py [YYYY-MM-DD]
```

- 不传日期 → 今天
- 扫描 `~/.dsh/sessions/`, 提取目标日期 (CST) 的 user/assistant 对话
- 自动写入 `04_agent/conversation/YYYY-MM-DD.md`
- 可加 `--out /path` 自定义输出, `--print-only` 只打印

### 第 2 步: 写总结 `03_daily/YYYY-MM-DD-summary.md`

**格式严格要求 — 只写 1 段, 严禁膨胀**:

```markdown
# 每日对话总结 — YYYY-MM-DD 星期X

## 📋 当日 dsh 对话总结 (按主题)

1. **主题名** (HH:MM-HH:MM) — 一句话说明发生了什么 (用户输入/决策/结果)
2. **主题名** ...
(或 0 时:)

- 今日 0 次 dsh 交互

---

*生成时间: HH:MM:SS · 数据源: YYYY-MM-DD.md*
```

**禁区**:
- ❌ 不要 "📦 产物摘要" 段
- ❌ 不要 "⏰ 心跳自动化执行表" 段
- ❌ 不要 "🎯 关键判断" / "⚠️ 待办" / "🔍 摸排方法修正" 等 LLM 自我反思段
- ❌ 不要 "已知 bug" 列表
- ❌ 不要堆 6 主题, 3-5 个就够了, 1 个也行

**判定阈值**:
- N 次交互 = 当日会话中 user/assistant 消息轮次, **不看注入式上下文**
- 主题归类 = 按"用户在同一时间段做的同一类事"分, 而不是按工具/产物分

### 第 3 步: vault 落盘 (本机不 commit)

vault 根目录: 优先 `$VAULT`, 否则 `~/Documents/steven_vault` / `~/webdav/steven_vault`。
本机 vault 不挂 git 时不需本地 commit; 在 VM 上这些文件同步后会自动纳入 git。

## 错误处理

| 错误 | 处理 |
|------|------|
| `~/.dsh/sessions/` 不存在 | 主题段写 "0 次 dsh 交互 (sessions 缺失)" |
| 无当日会话 | 主题段写 "0 次 dsh 交互", 不假装有主题 |
| 某会话无法解压 | 跳过该文件, 其余正常 |
| vault 不可写 | 警告但不阻塞, 把总结贴在对话里 |
| 时间戳跨日 (会话 23:00+ 延续到次日) | 按事件 timestamp 落 CST 日期, 不按 session start date |

## 反例 / 教训

- **2026-08-01** 前 3 版总结只跑 JSONL → 漏掉 ominiCrawl 跑批 + huashu PPT → 修 extract v2.0 加产物反查
- **2026-08-02 v1** 总结写 6 大段太啰嗦 → 用户说"少点废话, 我只要 2 部分" → 改格式
- **2026-08-10** skill 曾适配 Codex / WorkBuddy 双平台 (用户当时用 wb / codex)
- **2026-09-01** 用户全面改用 dsh, 明确要求: ① 取消 Apple Reminders (查不到 apple task) ② 数据源改为 **dsh 自身会话记录** `~/.dsh/sessions/` (不是 wb / codex)。同日修正: 曾误去 `.codex`/`.workbuddy` 目录找 — 那是旧平台, dsh 聊天记录在自己的 `~/.dsh/sessions/**/session.jsonl.zstd` (zstd 压缩 JSONL); 并记下 `user/message` / `assistant/message` / 毫秒时间戳 / 剔除注入上下文的提取规则。
