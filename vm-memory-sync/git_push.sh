#!/usr/bin/env bash
# git_push.sh - 将 memory 变更 commit + push 到 GitHub
# 用法: ./git_push.sh "commit message"

set -euo pipefail

COMMIT_MSG="${1:-"update memory"}"
MEMORY_ROOT="$HOME/.dsh/memory"

cd "$MEMORY_ROOT"

echo "[git_push] commit: $COMMIT_MSG"

git add MEMORY.md memory_summary.md context/*.md archive/*.md 2>/dev/null || true
git add -A

if git diff --cached --quiet; then
  echo "[git_push] 无变更，无需 push"
  exit 0
fi

git commit -m "$COMMIT_MSG"
git push origin main

echo "[git_push] ✅ push 完成"
