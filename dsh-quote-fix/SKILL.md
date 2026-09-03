---
name: dsh-quote-fix
description: dsh-service（@gehennawu/dsh-service）升级后一键恢复 MiniMax Coding Plan 额度适配
  —— 补回 quota-adapters.js 的 fetchMiniMaxUsage 适配器与 catalog 条目、client.js 的 kind
  下拉选项与中英翻译；附带升级后副作用检查清单（额度输入框圆环、dsh-automation 侧边栏按钮 CSS）。
  触发词：「修复额度」「MiniMax 额度」「额度适配器」「quota 适配」「升级后修复」「dsh-quote-fix」
version: 1.0.0
disable-model-invocation: true
---

# dsh-quote-fix — dsh-service 升级后恢复 MiniMax 额度适配

dsh-service 每次 npm 升级都会从 npm 重新拉包，覆盖 `quota-adapters.js` 与 `client.js`，
导致自定义的 MiniMax Coding Plan 额度适配器丢失（额度查询面板里没有 MiniMax 选项，
或选中后无数据/报错）。本 skill 可一键重放补丁并给出验证步骤。

## 背景（2026-09-03 修复，dsh-service 0.40.0 → 1.4.1）

MiniMax 不在 dsh-service 原生适配器里（原生只到 deepseek/stepfun/kimi/siliconflow/
xiaomi/opencode-go/zai 等）。额度查询需要自定义适配器，本次修复共 3 个文件、5 处改动。

## 使用步骤

1. **探测安装路径**（脚本默认 `/home/ubuntu/.dsh/profiles/web/node_modules/@gehennawu/dsh-service`，
   可用 `DSSVC_DIR=/path/to/dsh-service ./apply.sh` 覆盖）
2. **运行 `./apply.sh`** —— 幂等，已应用的部分会自动跳过，重复执行安全
3. **运行 `./verify.sh`** —— 确认 5 处补丁全部就位
4. **重启 dsh-web**（需征得用户同意）使 client.js 变更生效，浏览器硬刷新
5. **手动验证额度**：设置 → dsh-service → 额度查询 → minimax-cn 卡片点刷新，
   应显示「5h 窗口」≈ 已用百分比 与「Weekly 窗口」已用百分比，与官网「我的用量」一致

## 补丁清单（见 patches/ 与 apply.sh）

| # | 文件 | 改动 |
|---|------|------|
| 1 | quota-adapters.js | 插入 `MINIMAX_CODING_PLAN_URL` 常量 + `fetchMiniMaxUsage` 函数（`const CLIPROXY_CODEX_USAGE_URL` 锚点前） |
| 2 | quota-adapters.js | catalog 数组 `stepfun-step-plan` 条目后插入 `createComposedAdapter({ kind: 'minimax', ... })` |
| 3 | client.js | 硬编码 kind 列表 `bt=["opencode-go",...,"cliproxy"]` 末尾加 `,"minimax"` |
| 4 | client.js | 中文翻译 `quota.kind.minimax":"MiniMax Coding Plan"` |
| 5 | client.js | 英文翻译 `quota.kind.minimax":"MiniMax Coding Plan"` |

## 铁律（曾经踩过的坑）

1. **绝不改 `settings.yaml` 给 `minimax-cn` 加 `baseURL: https://www.minimaxi.com`** ——
   minimax-cn 的 pi-ai 默认路由是 `https://api.minimaxi.com/anthropic`（Anthropic 协议），
   覆盖 baseURL 会破坏 LLM 路由（模型全部报 apikey 错误）。额度适配器应走
   `configuration: 'fixed'`（硬编码查询端点），不依赖 baseURL 自动识别。
2. **Authorization 头不能重复加 `Bearer ` 前缀** —— `discoverQuotaCredential` 已按
   `format: 'bearer'` 把凭据格式化为 `Bearer <key>`，适配器直接 `headers: { Authorization: token }` 用。
   再加前缀会变成 `Bearer Bearer sk-...` → MiniMax 返回 1004。
3. **MiniMax 响应没有 `data` 层** —— `model_remains` 在顶层：`{ base_resp, model_remains: [...] }`。
4. **percent 方向** —— API 返回 `current_interval_remaining_percent` / `current_weekly_remaining_percent`
   是「剩余百分比」，UI 进度条要「已用百分比」：`percent = 100 - remaining`。
5. **kindKey 决定 UI 渲染** —— `'time-limit'` 类型不渲染进度条（只显示 "MCP 配额" 空标签）；
   用 `'tokens-limit-u3-n5'`（5h）和 `'tokens-limit-u6-n1'`（weekly）才有进度条。
6. **status_code 1004 = 凭据无效**（"cookie is missing, log in again"）→ 映射为
   `credential-rejected`，触发 UI 的「控制台登录态已失效」提示。
7. **Key 来源** —— MiniMax key 存于 `~/.dsh/.credentials.yaml`（ref: `MINIMAX_API_KEY` / `MINIMAX_CN_API_KEY`），
   适配器 keyHints 用 `['MINIMAX_API_KEY']`；两份 key 值相同。

## 升级后副作用检查清单

- [ ] MiniMax 额度适配（本 skill 主目标）
- [ ] 额度输入框圆环：1.4.1 注册在 `conversation.input.right`，受 `quotaLookup` feature 门控，
      若消失先确认 feature 开关 → 再看 slot 注册时序（0.40.0 懒加载 vs 1.4.1 注册时判定）
- [ ] dsh-automation 侧边栏按钮：CSS_TEXT 开头 `.dsh-automation-sidebar-entry{display:none!important}`
      会被插件更新覆盖，需重加
- [ ] 重启 dsh-web 前必须征得用户同意（MEMORY 铁律）