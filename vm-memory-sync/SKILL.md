---
name: vm-memory-sync
description: 将本机 DSH memory 目录（~/.dsh/memory/）同步到 VM，或从 VM 拉回。memory 目录包含核心记忆、项目上下文和每日归档，通过 git + GitHub 在 Mac 与 VM 之间共享。
disable-model-invocation: true
---

# vm-memory-sync

DSH memory 目录跨 Mac / VM 同步工具。

## 目录结构

```
~/.dsh/memory/          ← 同步源/目标
├── MEMORY.md           ← 核心记忆（必须同步）
├── memory_summary.md    ← 记忆摘要
├── context/            ← 项目上下文（必须同步）
│   ├── crawl.md
│   ├── fund.md
│   ├── opencodex.md
│   └── vm.md
├── archive/            ← 每日日志（可选同步）
└── rollout_summaries/  ← 历史记录（不同步）
```

## 命令

### sync_to_vm
将本机 memory .md 文件同步到 VM（scp 单向推送）。

**触发条件**: 本机有新记忆需要 VM 知道时使用。

```bash
# 同步核心文件（context + 根目录 md，不含 archive）
~/.dsh/skills/vm-memory-sync/sync_to_vm.sh

# 查看详细输出
DEBUG=1 ~/.dsh/skills/vm-memory-sync/sync_to_vm.sh
```

### sync_from_vm
将 VM 上的 memory 文件拉回本机（scp 单向拉取）。

**触发条件**: 在 VM 上有新记忆需要本机知道时使用。

```bash
~/.dsh/skills/vm-memory-sync/sync_from_vm.sh
```

### setup_github
将 ~/.dsh/memory 接入 GitHub，实现 Mac 与 VM 通过 git 双向同步。

**首次使用前必须运行一次**。

```bash
~/.dsh/skills/vm-memory-sync/setup_github.sh <github-repo-url>
# 例: ~/.dsh/skills/vm-memory-sync/setup_github.sh https://github.com/tevenliang/steven-memory.git
```

### git_push（需先 setup_github）
将本机 memory commit + push 到 GitHub。

```bash
~/.dsh/skills/vm-memory-sync/git_push.sh "更新 MEMORY.md"
```

### git_pull（需先 setup_github）
从 GitHub 拉取 VM（或另一台机器）推送的记忆到本机。

```bash
~/.dsh/skills/vm-memory-sync/git_pull.sh
```

## 同步策略

- **核心文件**（始终同步）: MEMORY.md, memory_summary.md, context/*.md
- **归档文件**（可选）: archive/*.md（量大，按需同步）
- **不同步**: rollout_summaries/（太大，包含二进制产物）
- **不删除**: sync 脚本不会从目标机器删除文件，只推送同名文件的更新

## 故障排除

### scp 报错 "Host key verification failed"
确保 ~/.ssh/config 中 VM Host 已配置 StrictHostKeyChecking 或使用 ssh config 的 IdentityFile。

### git push 报错 "Authentication failed"
检查 GitHub token 是否有效：`gh auth status`

### VM 上找不到 ~/.dsh/memory/
运行一次 `sync_to_vm`，脚本会自动创建必要目录。
