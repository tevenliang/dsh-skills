#!/usr/bin/env bash
# sync_from_vm.sh - 将 VM 上的 memory 文件拉回本机
# 用法: ./sync_from_vm.sh

set -euo pipefail

VM_HOST="${VM_HOST:-vm}"
VM_USER="${VM_USER:-ubuntu}"
VM_PATH="/home/$VM_USER/.dsh/memory"
MEMORY_ROOT="$HOME/.dsh/memory"

CORE_FILES=(
  "MEMORY.md"
  "memory_summary.md"
)

CONTEXT_FILES=(
  "context/crawl.md"
  "context/fund.md"
  "context/opencodex.md"
  "context/vm.md"
)

log() { echo "[$(date '+%H:%M:%S')] $*"; }
warn() { echo "[$(date '+%H:%M:%S')] WARNING: $*" >&2; }

# 检查 VM 上文件是否存在
log "检查 VM 上的 memory 文件..."
ssh "$VM_HOST" "test -d $VM_PATH" || error "VM 上不存在 ~/.dsh/memory，先在 VM 上运行 sync_to_vm"

# 拉取核心文件（带确认）
BACKUP_DIR="$MEMORY_ROOT/vm_pull_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

for f in "${CORE_FILES[@]}"; do
  LOCAL="$MEMORY_ROOT/$f"
  if ssh "$VM_HOST" "test -f $VM_PATH/$f"; then
    # 先备份本地文件
    if [[ -f "$LOCAL" ]]; then
      cp "$LOCAL" "$BACKUP_DIR/$f"
      warn "备份本地 $f → $BACKUP_DIR/$f"
    fi
    scp -p "$VM_HOST:$VM_PATH/$f" "$LOCAL"
    log "  ✓ $f"
  else
    warn "VM 上无此文件，跳过: $f"
  fi
done

# 拉取 context 文件
mkdir -p "$MEMORY_ROOT/context"
for f in "${CONTEXT_FILES[@]}"; do
  LOCAL="$MEMORY_ROOT/$f"
  if ssh "$VM_HOST" "test -f $VM_PATH/$f"; then
    if [[ -f "$LOCAL" ]]; then
      cp "$LOCAL" "$BACKUP_DIR/$f"
      warn "备份本地 $f → $BACKUP_DIR/$f"
    fi
    scp -p "$VM_HOST:$VM_PATH/$f" "$LOCAL"
    log "  ✓ $f"
  else
    warn "VM 上无此文件，跳过: $f"
  fi
done

log "✅ 拉取完成: VM → Mac，本地备份在 $BACKUP_DIR"
