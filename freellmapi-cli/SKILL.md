---
name: freellmapi-cli
description: Freellmapi 本地网关 CLI 管理 — 配置 DSH 接入、诊断平台连通性、查看状态。触发词：「freellmapi 配置」「接入 freellmapi」「诊断 freellmapi」「freellmapi doctor」「freellmapi setup」「freellmapi 网关」
version: 1.0.0
author: Steven Liang
license: MIT
platforms:
  - linux
last_modified: 2026-08-31
disable-model-invocation: true
---

# Freellmapi CLI Skill

> **🔴 铁律：本 skill 仅用于查询和诊断，绝不允许通过 `setup-dsh` 命令覆盖用户的 DSH settings.yaml！**
> 如需修改 DSH 配置，必须手动编辑 settings.yaml 并征得用户明确同意。
> 所有配置变更（keys、models、fallback chain）都通过 freellmapi 内部管理（UI 或 SQLite），不通过 CLI 写入 DSH。

## 前置条件

freellmapi 已安装在本机（源码在 `/home/ubuntu/freellmapi-src/`），服务运行在 `http://127.0.0.1:31415`。
CLI 路径：`node /home/ubuntu/freellmapi-src/cli/dist/index.js`

## 命令速查

```bash
CLI="node /home/ubuntu/freellmapi-src/cli/dist/index.js"
URL="http://127.0.0.1:31415"
KEY=$(grep 'FREELLMAPI_KEY:' /home/ubuntu/.dsh/.credentials.yaml | awk '{print $2}')
```

### 1. 列出支持的 Agent

```bash
$CLI list
```

### 2. 给 DSH 生成配置（**仅预览，不写入**）

```bash
# ✅ 只用于预览/诊断，展示配置差异，不会修改任何文件
$CLI setup-dsh --url $URL --api-key $KEY --dry-run

# ❌ 绝不允许执行以下命令覆盖 DSH 配置！
# $CLI setup-dsh --url $URL --api-key $KEY  (禁止！)
```

**铁律：`setup-dsh` 命令只能加 `--dry-run` 参数预览，绝不能不加 `--dry-run` 直接执行！**

如果用户需要修改 DSH 配置，必须：
1. 先展示 diff（dry-run 结果）给用户确认
2. 手动编辑 `~/.dsh/settings.yaml`（用 edit 工具）
3. 征得用户明确同意后再重启 DSH web

### 3. 诊断平台连通性

```bash
# 诊断所有平台
$CLI doctor

# 诊断单个平台
$CLI doctor opencode
$CLI doctor openrouter
$CLI doctor cloudflare
$CLI doctor nvidia
```

`doctor` 会实际发送测试请求到 freellmapi，验证 routing 是否通。

### 4. 查看当前模型列表（从 CLI 获取）

```bash
# 列出所有 catalog 模型（含主模型标记）
curl -s -H "Authorization: Bearer $KEY" "$URL/v1/models" \
  | node -e "
const fs=require('fs');
const d=JSON.parse(fs.readFileSync('/dev/stdin','utf8'));
const models=d.data||[];
console.log('总模型数:',models.length);
// 显示 top 20
models.slice(0,20).forEach(m=>console.log(m.id));
"
```

### 5. 检查 freellmapi 服务状态

```bash
# 健康检查
curl -s "$URL/api/ping"

# 看进程是否在跑
pgrep -af "node dist/index" | grep freellmapi
```

### 6. 通过 CLI 查看 DSH 配置预览（不改文件）

```bash
$CLI setup-dsh --url $URL --api-key $KEY --dry-run 2>&1 | head -80
```

## 使用场景与流程

**场景 A：诊断平台连通性**
1. 运行 `doctor` 或 `doctor <platform>` 检查各平台状态
2. 根据输出结果判断问题（key 失效 / rate limit / 网络不通等）

**场景 B：查看 DSH 配置预览（只读）**
1. 运行 `setup-dsh --dry-run` 查看当前配置差异
2. **绝不执行正式的 setup-dsh**（不加 --dry-run）
3. 如果用户要求修改 DSH 配置，手动编辑 settings.yaml

**场景 C：排查 freellmapi 问题**
1. 运行 `doctor <platform>` 精确定位失败原因
2. 根据错误信息建议处理方案

## 注意事项

- 🔴 **铁律：绝不允许执行 `setup-dsh`（无 --dry-run）覆盖 DSH 的 settings.yaml**
- DSH settings.yaml 是用户的手动配置，由用户或助手手动编辑，不由 CLI 自动生成
- freellmapi 的配置变更（keys、models、fallback chain）通过 UI 或 SQLite 操作，不通过 CLI
- `doctor` 的诊断结果保存在 console 输出中，不会持久化
- CLI 的 `--url` 参数可以是公网地址（如 https://aiflare.cloud），但在本机用 loopback
- 本 skill 只用于**查询和诊断**，不用于写入 DSH 配置

## 常用快捷命令

```bash
# 一键诊断全部平台
CLI="node /home/ubuntu/freellmapi-src/cli/dist/index.js"
$CLI doctor

# 预览 DSH 配置（只读，不改文件）
$CLI setup-dsh --url http://127.0.0.1:31415 \
  --api-key $(grep 'FREELLMAPI_KEY:' /home/ubuntu/.dsh/.credentials.yaml | awk '{print $2}') \
  --dry-run 2>&1 | head -80
```
