# dsh-quote-fix — 升级后恢复 MiniMax 额度适配（2026-09-03 修复实录）

本次修复源于 dsh-service `0.40.0 → 1.4.1` 升级后 MiniMax Coding Plan 额度适配器丢失。
用户在额度查询面板选不到 MiniMax、或选中后报「cookie is missing / 无数据」。

## 修复的文件与位置（3 文件 5 处）

| # | 文件 | 改动 | 锚点 |
|---|------|------|------|
| 1 | `quota-adapters.js` | 插入 `MINIMAX_CODING_PLAN_URL` + `fetchMiniMaxUsage()` | `const CLIPROXY_CODEX_USAGE_URL = ...` 之前 |
| 2 | `quota-adapters.js` | catalog 加 `createComposedAdapter({ kind: 'minimax', ... })` | `stepfun-step-plan` 条目之后、`])` 之前 |
| 3 | `client.js` | 硬编码 kind 列表 `bt=[...]` 末尾加 `,"minimax"` | `bt=["opencode-go",...]` |
| 4 | `client.js` | 中文翻译 `quota.kind.minimax` | 中文段 `quota.kind.xiaomi-token-plan-cn` 之后 |
| 5 | `client.js` | 英文翻译 `quota.kind.minimax` | 英文段 `quota.kind.xiaomi-token-plan-cn` 之后 |

**明确不改**：`settings.yaml` 的 `minimax-cn` 保持 `apiKeyEnv: MINIMAX_CN_API_KEY`，
**绝不加 `baseURL: https://www.minimaxi.com`**（会破坏 LLM 路由）。

## 快速操作

```bash
cd ~/.dsh/skills/dsh-quote-fix
./apply.sh          # 幂等重放补丁
./verify.sh         # 校验 5 处就位
# 然后：征得用户同意 → systemctl --user restart dsh-web → 浏览器硬刷新
# 验证：设置 → dsh-service → 额度查询 → minimax-cn 刷新
```

## 根因与教训（每一条都踩过）

### 1. 双 Bearer 前缀 → 1004 "cookie is missing"
`discoverQuotaCredential()` 会按 kind 的 `format: 'bearer'` 把凭据预先格式化为
`Bearer <key>`。适配器 fetch 里**直接** `headers: { Authorization: token }` 用。
若再加 `Bearer ${token}` → 实际发出 `Bearer Bearer sk-...` → MiniMax 拒绝。
（首版报 1004 就是这个原因。）

### 2. 响应**没有 data 层**
真实返回 `{ base_resp, model_remains: [...] }`，`model_remains` 在**顶层**。
误读 `payload.data.model_remains` → 永远取不到 → 空窗口。

### 3. remaining ≠ used（方向反转）
API 字段名是 `current_interval_remaining_percent` / `current_weekly_remaining_percent`
代表**剩余百分比**。UI 进度条要**已用百分比**：`percent = 100 - remaining`。
（官网验证：5h 已用 8% ↔ API remaining 92；周 已用 95% ↔ remaining 5。）

### 4. kindKey 决定 UI 渲染
`kindKey: 'time-limit'` 不渲染进度条（只显示 "MCP 配额" 空标签）。
要用 `'tokens-limit-u3-n5'`（5h）与 `'tokens-limit-u6-n1'`（weekly）才有进度条。

### 5. status_code 1004 → credential-rejected
MiniMax 错误码：`1004` = "cookie is missing, log in again"（凭据缺失/无效）。
映射为 `credential-rejected`，UI 显示「控制台登录态已失效」。

### 6. 别用 baseURL 做自动识别
`minimax-cn` 的 pi-ai 默认路由是 `https://api.minimaxi.com/anthropic`（Anthropic 协议）。
覆盖 settings.yaml baseURL 会把 LLM 请求打向错误端点 → 所有模型报 apikey 错误。
额度适配器用 `configuration: 'fixed'`（硬编码查询端点）不依赖 baseURL。

### 7. Key 存放位置
`~/.dsh/.credentials.yaml`：
```
MINIMAX_CN_API_KEY: sk-cp-...   # LLM 路由用
MINIMAX_API_KEY:    sk-cp-...   # 额度适配器 keyHints 用
```
两者值相同。适配器 `keyHints: ['MINIMAX_API_KEY']`。

## 手工补丁素材

- `patches/quota-adapters.minimax.js` — 完整 fetchMiniMaxUsage（含注释）
- `patches/catalog-entry.js` — minimax catalog 条目
- `patches/client.js.changes.md` — client.js 三处改动说明

## 升级后副作用检查清单

- [ ] MiniMax 额度适配（本 skill 主目标）
- [ ] 额度输入框圆环：1.4.1 注册在 `conversation.input.right`，受 `quotaLookup` feature 门控；
      消失先查 feature 开关 → slot 注册时序（0.40.0 懒加载 vs 1.4.1 注册时判定）
- [ ] dsh-automation 侧边栏按钮：`CSS_TEXT` 开头
      `.dsh-automation-sidebar-entry{display:none!important}` 会被更新覆盖，需重加
- [ ] 重启 dsh-web 必须征得用户同意（MEMORY 铁律）