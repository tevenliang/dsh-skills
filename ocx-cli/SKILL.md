---
name: ocx-cli
description: opencodex 代理管理。当前 Mac 本机运行 opencodex(127.0.0.1:10100)，Mac Codex 通过
  custom provider 直连本地 opencodex；`ocx sync` 是按 opencodex 配置重新生成 Codex
  模型目录的正确机制（当前版本不改动 config.toml）。VM(175.178.210.156:10100) 为备用/旧路径。
disable-model-invocation: true
---

# opencodex CLI 管理

> ## ⚠️ 架构已变更（2026-08-25）
> 当前 **opencodex 运行在 Mac 本机**（`127.0.0.1:10100`，bun 进程），不再依赖 VM。
> Mac Codex 的 `config.toml` 中 `model_provider="custom"` 直连 `http://127.0.0.1:10100/v1`。
> **`ocx sync` 现在是正确机制**：按 opencodex 配置重新生成 Codex 模型目录（catalog），
> 当前版本实测 **不会改动 config.toml**（输出 "Codex config/journal untouched"）。
> VM(175.178.210.156:10100) 仅作备用/历史路径，以下 VM 章节保留供参考。

## 架构概览（当前：本地）

```
Mac Codex (~/.codex/config.toml)
   └─ model_provider = "custom" → http://127.0.0.1:10100/v1
        └─ 本地 opencodex (bun, 端口 10100)
             └─ 按模型名路由上游 provider：
                  minimax-cn/MiniMax-M3 / M2.7 → minimax
                  deepseek/deepseek-v4-flash / v4-pro → deepseek
                  openrouter-free (combo) → openrouter 免费额度
```

**标准工作流（本地）**：改 `~/.opencodex/config.json`（providers/combos/customModels）→ `ocx sync` 重新生成 Codex catalog → 重启 Codex 桌面端加载新目录。
**日常增删模型 / 编辑 combo 不必改 config**：用 `ocx models add`（注册目录没收录的模型）和 `ocx combo set`（重排 combo targets），两者都即时生效；dashboard 的 Models / Combos 页面即其 GUI 封装，用户可自行操作。
**限制目录只暴露配置内模型**：`ocx provider selected openrouter --set "<model>,<model>..."`（白名单=配置内模型，避免 openrouter 全量公开目录灌入 Codex）。

## VM 环境准备

```bash
ssh ubuntu@175.178.210.156
export PATH="$HOME/.npm-global/bin:$PATH"
alias ocx='env -u NODE_OPTIONS ocx'
```

## 核心命令（VM 端）

```bash
ocx start          # 启动代理（后台，localhost:10100）
ocx stop           # 停止代理
ocx status         # 代理状态
ocx ready --wait   # 等代理就绪

ocx provider list  # 已配置 provider
ocx provider add <名> --api-key <key>  # 加 provider
ocx provider test <名>  # 连通性测试

ocx models              # 当前暴露的模型（list）
ocx models list-custom  # 列出所有 customModels（裸名路由注册项）
```

## 模型增删命令（⚠️ 技能早期版本漏了这组，实际 CLI 支持）

opencodex 把「模型」分成两层，**加/删命令分属两组，不要混用**：

### A. `ocx models add / remove` —— 管 customModels（裸名路由注册）

给 **provider 目录没收录** 的模型注册一个裸名映射（等同于手动写 `config.json` 的 `customModels` 数组条目）。

```bash
# 注册一个 catalog 没广告的模型（裸名 → provider/modelId）
ocx models add <provider>/<modelId> \
  --display-name <展示名，不含斜杠> \
  --context-window <tokens，如 200000> \
  --modalities text,image

# 删除 custom model（按 UUID 或 provider/modelId）
ocx models remove <UUID | provider/modelId>

# 查看当前所有 custom 模型
ocx models list-custom
```

- **改动立即生效**（catalog sync），不需要重启服务。
- 仅用于「裸名注册」。例如 deepseek 目录里没有裸名 `deepseek-v4-flash` 时，用这条注册；若 provider 的 `models` 列表已含该名则无需。

### B. combo 的查看与编辑

```bash
# 查看所有 combo / 单个 combo 的当前 targets（只读，用于改动前后核对）
ocx combo list
ocx combo show <combo名>

# 编辑 combo 的 targets（覆盖式重列，本地架构即时生效）
ocx combo set <combo名> --targets provider/model[:weight],provider/model[:weight],...
# 等价 dashboard 操作：Combos 页拖拽/编辑 targets（failover 首位优先）
```

- **本地架构（Mac 本机）下 `ocx combo set` 是首选**：改完即时生效（catalog sync），无需重启，就是 dashboard 编辑按钮的 CLI 封装。
- **⚠️ `--targets` 是整列表覆盖**：必须重列全部 targets，漏列的会丢失；想"加一个"就先 `ocx combo show` 拿到现有列表，追加后再 set。
- **兜底 `minimax-cn/MiniMax-M2.7` 永远留最后一位**，任何操作都不要挪动/覆盖它。
- 删除整个 combo：`ocx combo remove <combo名>`（或 Python 改 config 删块）。
- *（历史备注：早期 VM 架构文档曾建议"编辑 combo 一律用 VM Python、弃用 combo set"；本地架构实测 combo set 稳定可靠，以本段为准。）*

### 两组的关系（重要）

| 你想做的 | 本地架构怎么做 | 说明 |
|---|---|---|
| 给 provider 注册一个目录没收录的模型 | `ocx models add` | 写 customModels，即时生效 |
| 往 openrouter-free combo 增删/排序模型 | `ocx combo set <名> --targets ...` | 覆盖式重列，即时生效，等价于 dashboard |
| 删掉整个 openrouter-free 路由 | `ocx combo remove <名>` | 或 Python 改 config 删块 |

> **统一规范（本地架构）**：模型注册用 `ocx models add`，combo 编辑用 `ocx combo set`；两者都即时生效（catalog sync），无需重启也无需改 config.json 文件。dashboard 的 Models / Combos 页面就是这些命令的 GUI 封装，**用户可自行在 dashboard 操作，不需找人改 config**。

## 三个常见 combo 操作场景（加模型 / 删模型 / 设默认）

> **前置知识**：combo 是 failover 虚拟模型，`targets` 是**有序数组**，按数组顺序依次尝试（第 0 个先试，失败跳下一个）。**`minimax-cn/MiniMax-M2.7` 是兜底，必须永远排在 `targets` 最后一位**，任何操作都不能覆盖或挪动它。combo 没有 `default` 字段——「设为默认」= 把目标挪到 `targets[0]`。
>
> **本地架构直接用 `ocx combo set`（见 B 段）即可，即时生效**。下方三段为 **VM 旧架构的历史参考**（当时 `ocx combo set` 在 VM 上不稳），若你用的是本地 opencodex 可忽略，直接用 `ocx combo set`；若确需 Python 兜底，注意改 **Mac 本机** `~/.opencodex/config.json` 并 `ocx restart`，**不要 SSH 到已不使用的 VM**。

### 场景 A：加一个模型进现有 combo（如 openrouter-free 新增 openrouter 免费模型）

**⚠️ 关键**：新模型插在**兜底 minimax 之前**，不能覆盖兜底。

```bash
# VM Python：在兜底前插入新模型
ssh ubuntu@175.178.210.156 'python3 - <<PY
import json, shutil, datetime
p="/home/ubuntu/.opencodex/config.json"
shutil.copy(p, p+".bak-"+datetime.datetime.now().strftime("%Y%m%d%H%M%S"))
c=json.load(open(p)); t=c["combos"]["openrouter-free"]["targets"]
new_model={"provider":"openrouter","model":"<厂商>/<模型>:free"}   # 替换成真实模型全名
if new_model not in t:
    t.insert(len(t)-1, new_model)   # 插在兜底(minimax)前
json.dump(c, open(p,"w"), ensure_ascii=False, indent=2)
print("targets now:", [x["model"] for x in t])
PY'
ssh ubuntu@175.178.210.156 'systemctl --user restart opencodex-proxy'
```

### 场景 1：删掉某条 target（某模型开始收费 / 不想用了）

**⚠️ 关键**：按 `model` 全名精确过滤，**绝不要把 minimax 兜底误删**（除非用户明确要删兜底）。

```bash
# VM Python：按 model 名移除
ssh ubuntu@175.178.210.156 'python3 - <<PY
import json, shutil, datetime
p="/home/ubuntu/.opencodex/config.json"
shutil.copy(p, p+".bak-"+datetime.datetime.now().strftime("%Y%m%d%H%M%S"))
c=json.load(open(p)); t=c["combos"]["openrouter-free"]["targets"]
remove_model="<厂商>/<模型>:free"   # 要删的模型全名
before=len(t)
t=[x for x in t if x["model"]!=remove_model]
assert any(x["model"]=="MiniMax-M2.7" for x in t), "ERROR: 兜底 minimax 被误删！"
assert len(t)==before-1, f"未找到要删的模型 {remove_model}"
json.dump(c, open(p,"w"), ensure_ascii=False, indent=2)
print("removed. targets now:", [x["model"] for x in t])
PY'
ssh ubuntu@175.178.210.156 'systemctl --user restart opencodex-proxy'
```

### 场景 2：把某条 target 设为默认（优先路由）

**⚠️ 关键**：failover 下 `targets[0]` = 默认/优先。把目标挪到数组首位，**兜底 minimax 仍留最后**。

```bash
# VM Python：把指定模型移到 targets[0]
ssh ubuntu@175.178.210.156 'python3 - <<PY
import json, shutil, datetime
p="/home/ubuntu/.opencodex/config.json"
shutil.copy(p, p+".bak-"+datetime.datetime.now().strftime("%Y%m%d%H%M%S"))
c=json.load(open(p)); t=c["combos"]["openrouter-free"]["targets"]
default_model="<厂商>/<模型>:free"   # 要设为默认的模型全名
hit=[x for x in t if x["model"]==default_model]
assert hit, f"未找到模型 {default_model}"
others=[x for x in t if x["model"]!=default_model]
c["combos"]["openrouter-free"]["targets"]=hit+others   # 默认置顶，兜底自动留最后
json.dump(c, open(p,"w"), ensure_ascii=False, indent=2)
print("reordered. targets now:", [x["model"] for x in c["combos"]["openrouter-free"]["targets"]])
PY'
ssh ubuntu@175.178.210.156 'systemctl --user restart opencodex-proxy'
```

> **改完统一验证（VM）**：
> ```bash
> ssh ubuntu@175.178.210.156 'systemctl --user is-active opencodex-proxy; curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:10100/v1/models -H "Authorization: Bearer $(cat ~/.opencodex/service-api-token)"'
> ```
> 这三个场景都只改 combo「内部」targets，**Mac catalog slug 不变、Mac 端文件不用动、绝不跑 `ocx sync`**；保险起见重启一下 Codex 桌面端清缓存（非强制）。

## 增删 combo 内部 targets 后的处理流程

**核心结论：改的是 combo「内部」failover 目标列表，不是新增/删除一个顶层模型。Mac 端 catalog 里的 slug 没变，所以 Mac 端任何文件都不用动，更不用 `ocx sync`。**

### 统一改法：VM Python 改 `config.json` + 重启

> 编辑 combo 只有这一种方式（已弃用 `ocx combo set`）：

```bash
# 改前自动备份（见上方三个场景的 Python 模板，已含 shutil.copy 备份）
# Python 编辑 combos.openrouter-free.targets（加 / 删 / 设默认见上方三个场景）
# 重启服务让配置生效
ssh ubuntu@175.178.210.156 'systemctl --user restart opencodex-proxy'
```

- 改完必须 `systemctl --user restart opencodex-proxy` 才生效
- 改动持久化进 `config.json`，重启服务不丢
- ⚠️ 必须传**完整列表**（加=插兜底前、删=按 model 过滤、设默认=重排），没有单条 add-target / remove-target

### Codex 侧要不要动？

| 场景 | 改 Mac? | 重启 Codex? |
|---|---|---|
| 在 openrouter-free 内增删 target（本文场景） | ❌ 不用（slug 没变） | 保险起见重启桌面端清缓存，非强制 |
| 新增全新 combo/模型（如 openrouter-free） | ✅ 必须在 catalog 加 slug | ✅ 必须重启桌面端 |

**原因**：Codex 发请求时写的是 `model: "openrouter-free"`，VM 收到后在内部按当前 targets 做 failover。targets 变了 VM 自己知道，Codex 完全无感。

### 一句话总结

> 增删 openrouter-free 内部 target → **VM Python 改 `config.json` + 重启 opencodex-proxy** → **绝不跑 `ocx sync`** → Codex 直接可用（清缓存就重启一下桌面端）。

## ✅ 正确机制：`ocx sync`（本地架构）

**本地 opencodex 架构下，`ocx sync` 是按 opencodex 配置重新生成 Codex 模型目录（catalog）的正确命令。**

- 当前版本实测：`ocx sync` 仅刷新 catalog 与模型缓存，**不改动 `config.toml`**（输出 "Codex config/journal untouched"）。
- 适合"opencodex 作为唯一标准源"场景：改完 `~/.opencodex/config.json` 后跑 `ocx sync` 即可让 Codex 目录与 opencodex 配置保持一致。
- 注意：`ocx sync` 会 APPEND opencodex 生成的条目，**不会自动删除旧条目**（含历史残留或 opencodex 自己从 provider 自动发现的多余模型）。
- **🧹 目录重置法（彻底对齐标准源）**：若 catalog 被旧条目/残留污染、想 100% 由 opencodex 重新生成，先把 catalog 的 `models` 置空（`{"models":[]}`）再 `ocx sync` 即可，无需手工逐条删。注意 opencodex 自身自动发现的模型（如 deepseek provider 的 `*-vision-exp`）不在此列——它们来自 opencodex 标准源，要去掉得在 `config.json` 的 `disabledModels` 加该 slug 后重 sync。
- 限制 openrouter 目录泛滥：先 `ocx provider selected openrouter --set "<配置内模型>"` 收紧白名单，再 `ocx sync`。
- **禁止手工改 `cc-switch-model-catalog.json`**：所有模型开放/关闭/显示名都在 `~/.opencodex/config.json`（或 opencodex dashboard）调整，再 `ocx sync`。手工改会被下次 sync 覆盖或造成不一致。

## 标准工作流：修改 VM 配置

### 1. 改前备份（必须）

```bash
ssh ubuntu@175.178.210.156
cp ~/.opencodex/config.json ~/.opencodex/config.json.bak-$(date +%Y%m%d%H%M%S)
```

### 2. 编辑 config.json

用 Python 安全编辑（避免 JSON 格式错误）：

```python
import json, sys
path = "/home/ubuntu/.opencodex/config.json"
with open(path) as f:
    cfg = json.load(f)

# 示例：修改 openrouter-free combo 的 targets
# cfg["combos"]["openrouter-free"]["targets"] = [...]

with open(path, "w") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
print("OK")
```

### 3. 重启服务

```bash
systemctl --user restart opencodex-proxy
systemctl --user is-active opencodex-proxy   # 应为 active
```

### 4. 端到端验证

```bash
# 健康检查
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:10100/v1/models \
  -H "Authorization: Bearer $(cat ~/.opencodex/service-api-token)"

# 测试 openrouter-free combo
curl -s -m 50 -X POST http://127.0.0.1:10100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(cat ~/.opencodex/service-api-token)" \
  -d '{"model":"openrouter-free","messages":[{"role":"user","content":"hi"}],"max_tokens":10}'
```

### 5. Mac 端刷新

改完 VM 配置后，**只需重启 Codex 桌面端**即可刷新模型选择器。不需要任何 Mac 端命令。

## 铁律（必须遵守）

1. **本地架构下 `ocx sync` 是正确机制**（刷新 Codex catalog，不改 config.toml）；VM 旧架构曾禁止，现已不适用
2. **改前必须备份 config.json**，改完必须重启 Codex + 端到端 curl 验证
3. **Mac catalog slug 与 opencodex 模型名一致**（如 `minimax-cn/MiniMax-M3`、`deepseek/deepseek-v4-flash`）

## 涉及的文件

| 位置 | 文件 | 作用 |
|---|---|---|
| VM | `/home/ubuntu/.opencodex/config.json` | 代理主配置（providers / combos / customModels） |
| VM | `~/.config/systemd/user/opencodex-proxy.service` | systemd 服务（Restart=always） |
| VM | `/home/ubuntu/.opencodex/service.log` | 服务日志 |
| VM | `/home/ubuntu/.opencodex/service-api-token` | API token（health check 用） |
| Mac | `~/.codex/config.toml` | Codex 配置（model_provider=custom → VM:10100） |
| Mac | `~/.codex/cc-switch-model-catalog.json` | 模型目录（6 个 slug，provider=custom） |

## 6 个可用模型 slug（Mac catalog，大小写须与 VM 模型名一致）

`MiniMax-M2.7`、`MiniMax-M2.7-highspeed`、`MiniMax-M3`、`deepseek-v4-flash`、`deepseek-v4-pro`、`openrouter-free`

> Mac catalog 条目必须含 `supported_reasoning_levels` 字段，否则整份 JSON 解析失败、Codex 起不来。

## 当前 VM 端 combo 状态

VM `config.json` 的 `combos` 仅剩 1 个：**`openrouter-free`**（openrouter 免费额度，含 `minimax-cn/MiniMax-M2.7` 兜底）。直连 provider 路由（minimax-cn / deepseek）不走 combo，由 `model` 字段直接指定。

> 实测坑：curl 测裸名 combo 时，`$'...'` 单引号内 `$c` 不展开会触发 `model too_small` 假报错；改用 Python 发 `/v1/responses` 请求（payload 用 `input:[{role,content}]` + `stream:true`）才准。

## 常见故障排查

| 症状 | 根因 | 修复 |
|---|---|---|
| 400 `unknown model` | 裸模型名无法路由 | combo 加 `"alias"` 字段；customModels 加裸名映射 |
| 服务「卡死」不响应 | 进程干净退出(status=0)，systemd 不拉起 | service 文件 `Restart=on-failure` 改为 `Restart=always` |
| Codex 启动报 `missing supported_reasoning_levels` | catalog JSON 有残缺条目 | 删残缺条目 + 修尾逗号 |
| Codex 默认模型报错 | config.toml model 写成 `combo/openrouter-free` | 改为裸名 `openrouter-free` |
| combo 路由到收费模型 | 目标里混入了非免费 provider | 以权威额度清单为准，删掉非免费 target |
| `/v1/models` 返回 500（Codex 不可用） | customModels 写成了**对象格式** `{"裸名":"provider/modelId"}` | 转为**数组格式** `[{provider,modelId,displayName}]` |
| 新 provider 不识别 | 用了 `id`/`base_url`/`type` 字段名 | 改用 opencodex 标准格式：`adapter`/`baseUrl`/`authMode`/`apiKey`/`models` |
| combo 被混入非预期 provider 目标 | 某次编辑把其他 provider 模型混入 | 删除非预期 target，或拆分独立 combo |
| openrouter-free 报 429 | OpenRouter 免费档每日 50 次用完（充值 $10 后 1000/天） | 额度问题非配置问题，等 UTC 0 点重置或充值 |
