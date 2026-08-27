#!/usr/bin/env bash
# git_pull.sh - 从 GitHub 拉取最新的 memory 到本机
# 用法: ./git_pull.sh

set -euo pipefail

MEMORY_ROOT="$HOME/.dsh/memory"
cd "$MEMORY_ROOT"

echo "[git_pull] 拉取 GitHub 最新 memory..."

git fetch origin
git stash 2>/dev/null || true

if git diff --quiet origin/main; then
  echo "[git_pull] 已是最新的，无需拉取"
else
  git pull --no-edit origin main
  echo "[git_pull] ✅ 拉取完成"
fi
