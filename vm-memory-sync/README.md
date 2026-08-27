# vm-memory-sync

DSH memory 目录跨 Mac / VM 同步工具。

## 文件结构

```
~/.dsh/skills/vm-memory-sync/
├── SKILL.md           # Skill 元数据和使用说明
├── sync_to_vm.sh      # Mac → VM（scp 推送）
├── sync_from_vm.sh    # VM → Mac（scp 拉取）
├── setup_github.sh    # 接入 GitHub remote
├── git_push.sh        # git commit + push
└── git_pull.sh        # git pull

~/.dsh/memory/         # 同步的源/目标目录
├── MEMORY.md
├── memory_summary.md
└── context/
```

## 快速开始

### 1. 同步本机 memory 到 VM
```bash
~/.dsh/skills/vm-memory-sync/sync_to_vm.sh
```

### 2. 从 VM 拉回 memory 到本机
```bash
~/.dsh/skills/vm-memory-sync/sync_from_vm.sh
```

### 3. 配置 GitHub 双向同步（可选）

```bash
# 首次：在 GitHub 创建空 repo 后运行
~/.dsh/skills/vm-memory-sync/setup_github.sh https://github.com/tevenliang/steven-memory.git

# 后续 push
~/.dsh/skills/vm-memory-sync/git_push.sh "更新记忆"

# 后续 pull
~/.dsh/skills/vm-memory-sync/git_pull.sh
```

## 设计原则

- **安全**: 不修改本机 memory，拉取前先备份到 `vm_pull_YYYYMMDD_HHMMSS/`
- **单向优先**: 优先用 scp 直推，不依赖 git
- **不覆盖**: sync 脚本只更新同名文件，不删除目标机器上的其他文件
- **GitHub 可选**: git 同步是可选增强，直接 scp 也能工作
