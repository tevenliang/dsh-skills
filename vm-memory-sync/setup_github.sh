#!/usr/bin/env bash
# setup_github.sh - 将 ~/.dsh/memory 接入 GitHub remote
# 用法: ./setup_github.sh <github-repo-url>
# 例: ./setup_github.sh https://github.com/tevenliang/steven-memory.git

set -euo pipefail

REPO_URL="${1:-}"

if [[ -z "$REPO_URL" ]]; then
  echo "用法: $0 <github-repo-url>"
  echo "例: $0 https://github.com/tevenliang/steven-memory.git"
  exit 1
fi

MEMORY_ROOT="$HOME/.dsh/memory"
cd "$MEMORY_ROOT"

echo "[setup] 将 ~/.dsh/memory 接入 GitHub..."

# 检查是否已有 remote
if git remote -v | grep -q origin; then
  echo "[setup] remote origin 已存在，先移除旧的..."
  git remote remove origin
fi

# 添加 remote
git remote add origin "$REPO_URL"
echo "[setup] 添加 remote: $REPO_URL"

# 检查 git auth
echo "[setup] 验证 GitHub 连接..."
git ls-remote --heads origin main > /dev/null 2>&1 && echo "[setup] ✅ GitHub 连接正常" || {
  echo "[setup] ⚠️  GitHub 连接失败，检查 token: gh auth status"
}

echo "[setup] 完成。下一步:"
echo "  1. 在 GitHub 创建空 repo（无 README）"
echo "  2. 运行: git push -u origin main"
echo "  3. VM 上 clone 该 repo 到 ~/.dsh/memory/"
