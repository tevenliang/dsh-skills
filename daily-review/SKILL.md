---
name: daily-review
description: >
  每日复盘 — Apple Reminders 完成情况 + 当日聊天记录主题归类。 Codex / WorkBuddy 双适配: 自动检测运行平台,
  对话数据源按平台切换。 总结文件只需 2 段: ① Apple Reminders (永远输出, 0 也写) ② 当日聊天主题归类。

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

生成当日复盘，**总结文件只需 2 段**:

1. **🟢 Apple Reminders 今日完成** — 从 reminders-cli 获取 (永远输出, 0 个也写明 "0 完成")
2. **📋 当日聊天总结** — 按平台切换数据源:
   - **Codex**     : `~/.codex/sessions/*.jsonl` 的 user/assistant 文本
   - **WorkBuddy** : `~/.workbuddy/projects/*/<session-uuid>.jsonl` 的**完整对话全文**
     (对话发生时即落盘, **可做当日复盘**, 无需 conversation_search 隔夜索引)
     - 文件名 uuid == `sessions.id`, 可关联标题/调用技能 (`plugin_context_json.microSceneIds`)
     - 注入式上下文 (system-reminder / user_info / cb_summary 等) 已剔除, 仅留用户真实提问+助手回答
     - `workbuddy.db` 的 `sessions` 表仅作标题/技能关联, 不再作为对话正文源

完整活动流水落 `04_agent/conversation/YYYY-MM-DD.md` 给 LLM 自己看, 总结文件落 `03_daily/YYYY-MM-DD-summary.md` 给用户看.

## 输出文件

- `04_agent/conversation/YYYY-MM-DD.md` — 当日完整流水 (产物+对话, 给 LLM 摸排用)
- `03_daily/YYYY-MM-DD-summary.md` — 给用户的极简总结, 只有上面 2 段

## 工作流程

### 第 0 步: 确定平台 (Codex / WorkBuddy)

脚本自动检测, 也可显式指定:

```bash
python3 extract_today_msgs.py                         # auto 检测
python3 extract_today_msgs.py --platform workbuddy   # 显式 WB
python3 extract_today_msgs.py --platform codex       # 显式 Codex
```

检测优先级:
1. `--platform` 显式参数
2. 环境变量: WB 设了 `WORKBUDDY_APP_NAME` / `WORKBUDDY_CONFIG_DIR` → workbuddy
3. 数据存在性: `~/.codex/sessions` 有 JSONL → codex; 否则 workbuddy

> 调用本 skill 的 agent 一定知道自己是哪个平台, 若 auto 不确定就显式传 `--platform`。

### 第 1 步: 获取 Reminders 当日完成 (按目标日期, 非机器"今天")

⚠️ **务必按目标日期 YYYY-MM-DD 查, 不要写死 `done 0`**。自动化若在执行时机器时钟已滚到次日, `done 0` 会查错天 (返回 0)。
目标日期 = 第 2 步 extract 用的同一个 `YYYY-MM-DD`。先算天数差 `N`, 再 `done N`:

```bash
# $TARGET=目标日期(如 2026-08-12), 与 extract 的参数一致
N=$(python3 -c "import datetime,sys; t=datetime.date.fromisoformat('$TARGET'); print((datetime.date.today()-t).days)")
~/.local/bin/reminders-cli done "$N"
# 交叉验证(日期区间, 注意 done-range 入参顺序为 起..止):
# ~/.local/bin/reminders-cli done-range $TARGET $TARGET
```

- `N=0` → 查今天; `N=1` → 查昨天 (机器时钟已跨日时自动化场景常见)。
- 若 `done N` 与目标不符, 用 `done-range <start> <end>` 兜底核对。

### 第 2 步: 摸排当日完整流水 (落 .md, 不进 .md-summary)

```bash
python3 ~/.agents/skills/PRODUCTIVITY/daily-review/scripts/extract_today_msgs.py [YYYY-MM-DD] [--platform codex|workbuddy]
```

脚本按平台扫描:

- **产物层 (双平台共用)**: vault crawl 报告 / huashu PPT 快照 / subscription / `/tmp` 工程 / 自动化配置 / vault git 状态
  - `/tmp` 与自动化配置按平台走不同目录 (codex→`/tmp/codex_*`+`~/.codex/automations`; workbuddy→`/tmp/workbuddy*`+`~/.workbuddy/automations`)
- **对话层 (按平台)**:
  - codex     → 解析 session JSONL, 配对 user/assistant 文本
  - workbuddy → 读 `~/.workbuddy/projects/*/<uuid>.jsonl` **完整对话全文**, 按 `timestamp` 毫秒时间戳过滤当日, 每个今日会话 = 一条主题记录 (真实 user/assistant 文本, 已剔除 system-reminder/user_info/cb_summary 等注入块)

可选参数:
- `YYYY-MM-DD` — 指定日期 (默认今天)
- `--products-only` — 只输出产物部分
- `--platform` — 显式平台

完整输出写入 `04_agent/conversation/YYYY-MM-DD.md`。

⚠️ **WorkBuddy 数据源 (已修正)**: 完整对话正文**就在本地** — `~/.workbuddy/projects/*/<uuid>.jsonl`, 对话发生时即落盘, **可做当日复盘**, 不需要服务端、也不需要 `conversation_search` 隔夜索引。
- 早期误以为"正文在服务端、本地只有元数据"是**错的**; 实测本地 JSONL 含 user/assistant/工具调用/reasoning 全文。
- `conversation_search` 对 WB 会话索引滞后约 1 天 (隔夜), 因此**不再用于当日复盘**; 若要做历史会话回溯 (非当日), 才考虑它。
- `sessions` 表仅作标题/调用技能关联, 不再是对话正文源。

### 第 3 步: 写总结 `03_daily/YYYY-MM-DD-summary.md`

**格式严格要求 — 只写 2 段, 严禁膨胀**:

```markdown
# 每日工作总结 — YYYY-MM-DD 星期X

## 🟢 Apple Reminders 今日完成 (N 项)

- list: title @ HH:MM
- ...

(或 0 时:)

- 今日 0 完成

## 📋 <平台> 今日聊天总结 (按主题)

1. **主题名** (HH:MM-HH:MM) — 一句话说明发生了什么 (用户输入/产物/决策/结果)
2. **主题名** ...
(或 0 时:)

- 今日 0 次 <平台> 交互

---

*生成时间: HH:MM:SS · 数据源: YYYY-MM-DD.md*
```

`<平台>` 取值: Codex 用 "Codex", WorkBuddy 用 "WorkBuddy"。
WB 主题命名建议基于本地 JSONL 同日全文中的**用户真实首问**, 关联 `sessions` 表 `custom_title`(技能名) 作辅助, 按时间段合并同类项。

**禁区**:
- ❌ 不要 "📦 产物摘要" 段 (用户不要看, 产物已经在 subscription / 报告里)
- ❌ 不要 "⏰ 心跳自动化执行表" 段
- ❌ 不要 "🎯 关键判断" / "⚠️ 待办" / "🔍 摸排方法修正" 等 LLM 自我反思段
- ❌ 不要 "已知 bug" 列表 (那是 ad_hoc notes 的事)
- ❌ 不要堆 6 主题, 3-5 个就够了, 1 个也行

**判定阈值**:
- N 次交互 = 平台数据源找到的当日会话/对话轮次, **不看 reminder、heartbeat、skill injection**
- 主题归类 = 按"用户在同一时间段做的同一类事"分, 而不是按工具/产物分

### 第 4 步: vault 版本管理 (本机不 commit)

⚠️ **本机 `~/Documents/steven_vault` 不挂 git, 不要再跑 `git commit`** (会报 `not a git repository`, 属预期)。
vault 的 git 仓库在 **VM** 上, VM 会**定时自动 commit 所有修改**。

所以本步只需: 确认两个文件已写入本机 vault 即可, 它们在 WebDAV 同步到 VM 后会被自动纳入 git。
无需本地 commit, 也无需 SSH 到 VM 手动 commit。

> 若日后需在 VM 查历史: SSH 到 VM 后在 vault 的 git 仓库里操作 (本机无 git)。

## 错误处理

| 错误 | 处理 |
|------|------|
| reminders-cli 不存在 | "0 完成" 注 "无法获取" |
| 无今日 JSONL (codex) | 主题段写 "0 次 Codex Desktop 交互", 不假装有主题 |
| workbuddy.db 不存在 (workbuddy) | 主题段写 "0 次 WorkBuddy 交互 (db 缺失)" |
| 全天 0 会话 + 0 reminder | 总结文件仍写 "0 完成" + "0 次交互" 两行 |
| vault 不可写 | 警告但不阻塞, 把总结贴在对话里 |
| 时间戳跨日 (session 23:00+ 延续到次日) | 按事件 timestamp 落到 CST 日期, 不按 session start date |

## 双平台路径

vault 根目录按运行平台解析:
- 优先读 `$VAULT` 环境变量
- 未设置时: macOS → `~/Documents/steven_vault`

平台检测:
- Codex: `~/.codex/sessions/rollout-*.jsonl` 存在
- WorkBuddy: 环境变量 `WORKBUDDY_APP_NAME` / `WORKBUDDY_CONFIG_DIR` 命中, 或 `workbuddy.db` 存在

## 反例 / 教训

- **2026-08-01** 前 3 版总结跑了 `extract_today_msgs.py` 但只看 JSONL → 漏掉 ominiCrawl 跑批 + huashu PPT 8 版 + /tmp 工程 → 修 extract_today_msgs.py v2.0 加 6 层产物反查
- **2026-08-02 v1** 总结写了 6 大段 (产物/心跳/判断/待办/摸排方法) 太啰嗦 → 用户说"少点废话, 我只要 2 部分" → 改格式
- **2026-08-02 v2** 已采用本格式作为标准
- **2026-08-04** summary 路径从 `04_agent/conversation/` 改到 `03_daily/` (用户要求, 当日总结放更显眼位置)
- **2026-08-10** skill 从纯 Codex 适配重构为 Codex/WorkBuddy 双适配: WB 对话源改为 `workbuddy.db` 的 `sessions` 表 (元数据级, 不含全文); 新增 `--platform` 参数 + auto 检测 (环境变量/数据存在性)
- **2026-08-11** 修正重大误判: 实测 WB 完整对话正文**就在本地** `~/.workbuddy/projects/*/<uuid>.jsonl` (对话发生时即落盘, 可做当日复盘), 之前"正文在服务端/本地只有元数据"是错的。WB 主数据源改为本地 JSONL 同日全文 (`extract_wb_fulltext`), `conversation_search` 仅作历史回溯 (对 WB 滞后约 1 天, 不再用于当日)。`workbuddy.db` 仅留作标题/技能关联。
