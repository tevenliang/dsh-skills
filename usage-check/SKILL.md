---
name: usage-check
description: API 用量查询 + VM 资源监控（JSON 结构化输出）— MiniMax Coding
  Plan（5h窗口+周统计双健康检查）、Tavily API 额度、OpenRouter 余额、VM (Hermes)
  硬盘/内存/CPU。触发词：「用量查询」「查用量」「API 用量」「查配额」「OpenRouter 余额」「VM 状态」
version: 6.0.0
disable-model-invocation: true
---

# 用量查询 + VM 资源监控 Skill

四个独立只读检查，所有模块输出 **structured JSON**。

## Overview

| 模块 | 状态 | 数据源 |
|------|------|--------|
| **MiniMax Coding Plan** | ✅ 启用 | `https://www.minimaxi.com/v1/api/openplatform/coding_plan/remains` |
| **Tavily API** | ✅ 启用 | `https://api.tavily.com/usage` |
| **OpenRouter** | ✅ 启用 | `https://openrouter.ai/api/v1/credits` |
| **VM (Hermes) 资源** | ✅ 启用 | SSH `ubuntu@175.178.210.156`（无额外凭证） |

## 架构

```
/home/ubuntu/.dsh/skills/usage-check/scripts/
├── usage-check.sh           # ⭐ 统一入口
├── minimax-check.sh         # MiniMax Coding Plan
├── tavily-check.sh          # Tavily API
├── openrouter-check.sh        # OpenRouter
└── vm-check.py              # VM SSH 查询（Python3，输出 JSON）
~/.opencodex/scripts/
└── (no wrapper needed)
```

## 用法

```bash
# 默认：人类可读汇总（all = minimax + vm + tavily + openrouter）
bash /home/ubuntu/.dsh/skills/usage-check/scripts/usage-check.sh

# 合并 JSON 输出（适合 cron / 日志）
bash /home/ubuntu/.dsh/skills/usage-check/scripts/usage-check.sh all json

# 单模块
bash /home/ubuntu/.dsh/skills/usage-check/scripts/usage-check.sh minimax
bash /home/ubuntu/.dsh/skills/usage-check/scripts/usage-check.sh tavily
bash /home/ubuntu/.dsh/skills/usage-check/scripts/usage-check.sh openrouter
bash /home/ubuntu/.dsh/skills/usage-check/scripts/usage-check.sh vm

# 单模块 + JSON
bash /home/ubuntu/.dsh/skills/usage-check/scripts/usage-check.sh minimax json
bash /home/ubuntu/.dsh/skills/usage-check/scripts/usage-check.sh tavily json
bash /home/ubuntu/.dsh/skills/usage-check/scripts/usage-check.sh openrouter json
bash /home/ubuntu/.dsh/skills/usage-check/scripts/usage-check.sh vm json
```

### 单脚本独立调用

```bash
bash /home/ubuntu/.dsh/skills/usage-check/scripts/minimax-check.sh
bash /home/ubuntu/.dsh/skills/usage-check/scripts/tavily-check.sh
bash /home/ubuntu/.dsh/skills/usage-check/scripts/openrouter-check.sh
python3 /home/ubuntu/.dsh/skills/usage-check/scripts/vm-check.py
```

## 前置条件

凭证统一存放在 `~/.agents/credentials/`（无例外）:

| 凭证 | 路径 | 字段 |
|------|------|------|
| MiniMax API Key | `~/.agents/credentials/minimax.json` | `{"api_key": "sk-cp-..."}` |
| Tavily API Key | `~/.agents/credentials/tavily.json` | `{"api_key": "tvly-..."}` |
| OpenRouter API Key | `~/.agents/credentials/openrouter.json` | `{"api_key": "sk-or-..."}` |

VM 无需额外凭证（使用 SSH key 免密登录）。缺失凭证会输出 `{"error": "..."}` JSON 而非静默失败。建议 `chmod 600 ~/.agents/credentials/*.json`。

## 健康检查阈值

### MiniMax 窗口（5h 和 weekly 共用）

基于 **剩余百分比**（注意是「剩余」不是「已用」）:

| 剩余百分比 | 健康度 | emoji |
|----------|--------|-------|
| `≥ 50%` | 充足 | 💚 |
| `20% ≤ p < 50%` | 正常 | 🟡 |
| `10% ≤ p < 20%` | 紧张 | 🔴 |
| `< 10%` | 紧急 | 🚨 |
| `status=3` | 未启用 | ⚪ |

### Tavily（基于已用百分比）

| 已用百分比 | 健康度 | emoji |
|----------|--------|-------|
| `< 50%` | 充足 | 💚 |
| `50% ≤ p < 75%` | 正常 | 🟡 |
| `75% ≤ p < 90%` | 紧张 | 🔴 |
| `≥ 90%` | 紧急 | 🚨 |

### OpenRouter（基于剩余金额 USD）

| 总余额 | 健康度 | emoji |
|---------|--------|-------|
| `≥ $50` | 充足 | 💚 |
| `$10 ≤ x < $50` | 正常 | 🟡 |
| `$1 ≤ x < $10` | 偏低 | 🔴 |
| `< $1` | 即将耗尽 | 🚨 |

### VM

| 指标 | 阈值 | 紧张 | 紧急 |
|------|------|------|------|
| 硬盘已用% | `≥75%` 紧张，`≥90%` 紧急 | 🔴 | 🚨 |
| 内存已用% | `≥75%` 紧张，`≥90%` 紧急 | 🔴 | 🚨 |
| CPU 使用% | `≥70%` 紧张，`≥90%` 紧张 | 🔴 | 🚨 |

## JSON Schema

### 错误格式（所有模块统一）

```json
{"error": "凭证文件不存在: /path/to/cred", "fetched_at": "2026-07-13 14:00:00"}
```

### MiniMax

```json
{
  "models": [{
    "model": "general",
    "5h_window": {
      "start_time": "07-13 10:00", "end_time": "07-13 15:00",
      "remaining_time": "30分钟", "remaining_time_seconds": 1810,
      "used_percent": 40, "remaining_percent": 60,
      "status": "active", "status_text": "生效",
      "health": "充足", "health_emoji": "💚"
    },
    "weekly_window": {
      "start_time": "07-13 00:00", "end_time": "07-20 00:00",
      "remaining_time": "6.4天", "remaining_time_seconds": 552610,
      "used_percent": 9, "remaining_percent": 91,
      "status": "active", "status_text": "生效",
      "boost_percent": 15.0,
      "health": "充足", "health_emoji": "💚"
    }
  }],
  "fetched_at": "2026-07-13 14:00:00"
}
```

### Tavily

```json
{
  "plan": "Researcher", "limit": 1000, "used": 27,
  "used_percent": 2.7, "remaining": 973, "search_usage": 27,
  "health": "充足", "health_emoji": "💚",
  "fetched_at": "2026-07-13 14:00:00"
}
```

### OpenRouter

```json
{
  "total_credits": 10,
  "total_usage": 0.15,
  "remaining": 9.85,
  "health": "正常",
  "health_emoji": "🟡",
  "fetched_at": "2026-07-13 14:00:00"
}
```

### VM

```json
{
  "disk":   {"total_gb": 40, "used_gb": 31, "avail_gb": 7, "used_percent": 82, "health": "紧张", "health_emoji": "🔴"},
  "memory": {"total_mb": 3723, "used_mb": 2105, "avail_mb": 1617, "used_percent": 56.5, "health": "正常", "health_emoji": "🟡"},
  "cpu":    {"used_percent": 26.8, "load_avg": "4.12, 3.51, 3.25", "health": "充足", "health_emoji": "🟢"},
  "host": "175.178.210.156",
  "fetched_at": "2026-08-18 18:37:39"
}
```

## 人类可读输出样例

```
=== MiniMax 用量 ===
【general】
  ⏰ 5h窗口: 08-20 00:00 ~ 08-20 05:00 (生效) | 剩余 4.9小时
  📊 5h用量: 2% 已用 | 98% 剩 | 💚 充足
  📅 本周窗口: 08-17 00:00 ~ 08-24 00:00 (生效) | 剩余 4.0天
  📈 本周用量: 71% 已用 | 29% 剩 | 🟡 正常
  ⏱️ 抓取时间: 2026-08-20 00:07:47

=== VM (Hermes) 状态 ===
💾 硬盘 [40G total]
   已用: 31G / 40G (83%) | 剩余 7G | 🔴 紧张
🧠 内存 [3723M total]
   已用: 2521M / 3723M (67.7%) | 可用 1201M | 🟡 正常
⚙️  CPU [使用 6.7% | load 0.01, 0.13, 0.27] | 🟢 充足
   ⏱️ 抓取时间: 2026-08-20 00:07:48

=== Tavily 用量 ===
📡 Tavily [Researcher]
   已用: 326 / 1000 (32.6%)
   剩余: 674 credits
   搜索消耗: 326 credits
   健康度: 💚 充足
   ⏱️ 抓取时间: 2026-08-20 00:07:51

=== OpenRouter 余额 ===
🌐 OpenRouter [USD]
   💰 总充值: $10.00
   📊 已消费: $0.15
   ✅ 剩余: $9.85 | 🟡 正常
   ⏱️ 抓取时间: 2026-08-20 00:07:55
```

## 已知问题 / 陷阱

1. **⚠️ MiniMax 用量端点是 `/v1/api/openplatform/coding_plan/remains`**: 唯一可用 URL 为 `https://www.minimaxi.com/v1/api/openplatform/coding_plan/remains` (GET)

2. **⚠️ MiniMax 响应字段不是 total/usage 计数**: 真实数据在 `current_interval_remaining_percent` / `current_weekly_remaining_percent`

3. **⚠️ Tavily `/usage` 是唯一可用账户端点**: `/credits`、`/me`、`/remaining_credits` 等均 404

4. **⚠️ Coding Plan Key 完整性**: Key 必须完整（125 字符），本地存储被截断会导致 1004 login fail

5. **⚠️ 凭证文件权限**: 建议 `chmod 600 ~/.agents/credentials/*.json`

6. **API 限速**: MiniMax Coding Plan 查询建议间隔 ≥ 30s，**脚本不内置限速**，由调用方控制

7. **curl 超时**: 三个脚本都设了 10-15s 超时，无网络时输出 `{"error": "API 请求超时"}`

8. **python3 依赖**: Mac 上 `/usr/bin/python3` 即可，无需额外环境

9. **⚠️ `weekly_boost_permille` 是千分比**: 1500 = 15.0%，脚本已 `/100` 转换

## 相关 Skills

- `minimax-image-generation`: 图片生成（消耗 MiniMax 配额）
- `minimax-web-search`: MiniMax Web Search
- `web-search`: 通用 Web 搜索（含 Tavily 后端）
- `crawl`: 网页爬取（可能调用 OpenRouter 做内容分析）

