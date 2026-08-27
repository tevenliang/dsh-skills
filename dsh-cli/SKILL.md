---
name: dsh-cli
metadata:
  version: 1.0.0
description: >
  DeepSeek Harness (DSH) CLI 完整命令参考。覆盖 dsh 启动 profile、web 服务、插件管理等全部命令与选项。
disable-model-invocation: true
---

# dsh-cli — DeepSeek Harness 命令行参考

## 全局概述

`dsh` 启动一个 profile（插件 bundle 补丁层的有序栈，叠加在你的自定义覆盖之上）。

```
dsh [options] [command] [args...]
```

## 顶层命令

| 命令 | 说明 |
|------|------|
| `dsh web [options] [args...]` | 启动 web profile（等价于 `--profile web`），web app 自身参数紧随其后 |
| `dsh plugin [options] [args...]` | 管理某 profile 的插件，剩余参数转发给该 profile 目录下的 pnpm |
| `dsh --profile <name> [args...]` | 启动指定 profile（如 `web`/`tui`/`headless`/`desktop`） |
| `dsh --help` / `-h` | 显示帮助 |
| `dsh -V` / `--version` | 输出版本号 |

## 顶层选项

| 选项 | 说明 |
|------|------|
| `--profile <name>` | 要启动的 profile，位于 `$DSH_HOME/profiles` 下 |
| `--patch <path>` | 在 profile 层之后额外叠加的补丁列表（可重复） |
| `--dump-config` | 打印组合后的 profile 树并退出 |
| `--dump-default-config` | 打印去掉用户层和 `--patch` 覆盖后的默认 profile 树并退出 |

## `dsh web` 子命令选项

```
dsh web [options] [args...]
```

| 选项 | 说明 |
|------|------|
| `--host <host>` | 绑定 host |
| `--no-open` | 不在默认浏览器打开 Web UI |
| `--port <port>` | 监听端口；传 `0` 让 OS 自动选空闲端口 |
| `--trusted-host <authority...>` | 额外的 `/api` 浏览器信任围栏接受的 authority（host 或 host:port，可重复） |
| `-h`, `--help` | 显示帮助 |

## `dsh plugin` 子命令（转发到 pnpm）

`dsh plugin --profile <name> <pnpm 子命令>`，等价于在 profile 目录跑 pnpm。

### 常用插件管理命令

| 命令 | 说明 |
|------|------|
| `dsh plugin --profile web add <pkg>` | 安装插件到 web profile（⚠️ workspace 根需加 `-w`） |
| `dsh plugin --profile web remove <pkg>` | **正确删除插件**（会更新依赖树，避免误删） |
| `dsh plugin --profile web update <pkg> --latest` | 更新插件到最新版 |
| `dsh plugin --profile web list` | 列出已安装的插件（树形） |
| `dsh plugin --profile web ls` | 同上 |
| `dsh plugin --profile web outdated` | 检查过期插件 |
| `dsh plugin --profile web why <pkg>` | 显示某包为何被依赖 |

### 其他 pnpm 命令（同样可用）

`install` / `i` · `rm` / `remove` · `ln` / `link` · `unlink` · `up` / `update` ·
`audit` · `outdated` · `why` · `create` · `dlx` · `exec` · `run` · `config` ·
`init` · `publish` · `stage`

⚠️ `pnpm` 9+ 在 workspace 根有 `ERR_PNPM_ADDING_TO_ROOT` 限制：安装/更新命令末尾要加 `-w`（`--workspace-root`）。

## 实用示例

```bash
# 启动 web profile（不自动开浏览器）
dsh web --no-open --port 3080

# 启动指定 profile
dsh --profile tui

# 恢复某个 session
dsh --profile tui --resume <session>

# 一次性回答任务后退出
dsh --profile headless "run the tests"

# 安装插件（workspace 根必须 -w）
dsh plugin --profile web add <package> -w

# 正确删除插件（避免崩溃）
dsh plugin --profile web remove <package>

# 更新插件（跨大版本加 --latest）
dsh plugin --profile web update <package> --latest -w

# 列出插件
dsh plugin --profile web list

# 自定义 profile + 额外补丁层
dsh --profile tui --patch ./extra.yml

# 查看组合后的配置（调试用）
dsh --dump-config
```

## 重启 dsh web 的正确方式（单命令 + 自动验证反馈）

⚠️ **关键坑**：
1. `nohup ... &` 放后台后命令立即返回、无输出 → 必须**主动验证并回显结果**，否则用户不知道重启成没成。
2. 直接编辑 `package.json` 删插件会导致崩溃；必须用 `dsh plugin --profile web remove <pkg>`。
3. 端口冲突：重启前必须彻底杀掉旧进程，否则 `EADDRINUSE: 3080` 导致新进程启动失败。

### 单条命令（杀 → 重启 → 自动验证，返回明确反馈）

```bash
pkill -f "dsh web" 2>/dev/null; sleep 2; nohup dsh web --no-open --port 3080 > /tmp/dsh-web.log 2>&1 & sleep 3; echo "【重启反馈】HTTP:$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3080) (200=成功)"; ps aux | grep "dsh web" | grep -v grep | awk '{print "新进程PID:"$2}'
```

执行后**必须把输出反馈给用户**，例如：
- `HTTP:200 新进程PID:76530` → 明确告诉用户"重启成功，服务已就绪"
- 如果不是 200 → 查看 `/tmp/dsh-web.log` 排查（最常见是 EADDRINUSE 端口被占）。

### 分步写法

```bash
# 1. 杀旧进程
pkill -f "dsh web" 2>/dev/null
# 2. 等端口释放
sleep 2
# 3. 后台启动新进程
nohup dsh web --no-open --port 3080 > /tmp/dsh-web.log 2>&1 &
# 4. 等 3 秒再验证（关键！否则新进程未就绪会误报失败）
sleep 3
# 5. 明确的验证反馈
curl -s -o /dev/null -w "HTTP:%{http_code}\n" http://127.0.0.1:3080
ps aux | grep "dsh web" | grep -v grep
# 然后向用户报告：「重启成功，HTTP 200」或失败原因
```

⚠️ **失败排查**：验证非 200 时看 `/tmp/dsh-web.log`，几乎都是 `EADDRINUSE`（旧进程没死透）。用 `ps aux | grep "dsh web" | grep -v grep | awk '{print $2}' | xargs kill -9` 强杀后再重启。
