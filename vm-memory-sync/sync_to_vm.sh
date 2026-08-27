#!/usr/bin/env bash
# sync_to_vm.sh - 将本机 memory .md 文件同步到 VM
# 用法: ./sync_to_vm.sh

set -euo pipefail

VM_HOST="${VM_HOST:-vm}"
VM_USER="${VM_USER:-ubuntu}"
VM_PATH="/home/$VM_USER/.dsh/memory"
MEMORY_ROOT="$HOME/.dsh/memory"

# 核心文件（必须同步）
CORE_FILES=(
  "MEMORY.md"
  "memory_summary.md"
)

# context 目录下的所有 md
CONTEXT_FILES=(
  "context/crawl.md"
  "context/fund.md"
  "context/opencodex.md"
  "context/vm.md"
)

log() { echo "[$(date '+%H:%M:%S')] $*"; }
warn() { echo "[$(date '+%H:%M:%S')] WARNING: $*" >&2; }
error() { echo "[$(date '+%H:%M:%S')] ERROR: $*" >&2; exit 1; }

# 检查源文件是否存在
MISSING=0
for f in "${CORE_FILES[@]}" "${CONTEXT_FILES[@]}"; do
  if [[ ! -f "$MEMORY_ROOT/$f" ]]; then
    warn "源文件不存在: $f，跳过"
    ((MISSING++)) || true
  fi
done

# 在 VM 上创建目录
log "创建 VM 目标目录..."
ssh "$VM_HOST" "mkdir -p $VM_PATH/context"

# 同步核心文件
log "同步核心文件到 VM..."
for f in "${CORE_FILES[@]}"; do
  if [[ -f "$MEMORY_ROOT/$f" ]]; then
    scp -p "$MEMORY_ROOT/$f" "$VM_HOST:$VM_PATH/"
    log "  ✓ $f"
  fi
done

# 同步 context 文件
log "同步 context/ 文件到 VM..."
for f in "${CONTEXT_FILES[@]}"; do
  if [[ -f "$MEMORY_ROOT/$f" ]]; then
    scp -p "$MEMORY_ROOT/$f" "$VM_HOST:$VM_PATH/${f%/*}/"
    log "  ✓ $f"
  fi
done

log "✅ 同步完成: Mac → VM ($VM_HOST:$VM_PATH)"
