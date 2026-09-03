#!/usr/bin/env bash
# dsh-quote-fix: 验证 MiniMax 适配补丁是否全部就位
# 用法: ./verify.sh [dsh-service安装目录]
set -u

CANDIDATES=(
  "${DSSVC_DIR:-}"
  "/home/ubuntu/.dsh/profiles/web/node_modules/@gehennawu/dsh-service"
  "$HOME/.dsh/profiles/web/node_modules/@gehennawu/dsh-service"
)
DSSVC_DIR="${1:-}"
if [ -n "$DSSVC_DIR" ]; then CANDIDATES=("$DSSVC_DIR"); fi

DSSVC_DIR=""
for d in "${CANDIDATES[@]}"; do
  if [ -n "$d" ] && [ -f "$d/quota-adapters.js" ] && [ -f "$d/client.js" ]; then
    DSSVC_DIR="$d"; break
  fi
done
if [ -z "$DSSVC_DIR" ]; then
  echo "✗ 未找到 dsh-service 安装目录，请用: ./verify.sh <path>" >&2
  exit 1
fi
echo "→ dsh-service 目录: $DSSVC_DIR"

export DSSVC_DIR
python3 << 'PYEOF'
import os, re

base = os.environ["DSSVC_DIR"]
adapters = open(os.path.join(base, "quota-adapters.js"), "rb").read()
client   = open(os.path.join(base, "client.js"), "rb").read()

checks = [
  ("P1a  fetchMiniMaxUsage 函数",      b"async function fetchMiniMaxUsage" in adapters),
  ("P1a  MINIMAX_CODING_PLAN_URL",      b"MINIMAX_CODING_PLAN_URL" in adapters),
  ("P1b  catalog kind: 'minimax'",      b"kind: 'minimax'" in adapters),
  ("P3   bt 数组含 minimax",            b"\"minimax\"" in client and re.search(rb'bt=\[[^\]]*"minimax"[^\]]*\]', client) is not None),
  ("P4/5 翻译 quota.kind.minimax 中文", b"quota.kind.minimax" in client and client.count(b"quota.kind.minimax") >= 2),
  ("P4/5 翻译 quota.kind.minimax 英文", client.count(b'"quota.kind.minimax":"MiniMax Coding Plan"') == 2),
]

allok = True
for name, passed in checks:
    print(("  ✓ " if passed else "  ✗ ") + name)
    allok = allok and passed

print()
if allok:
    print("✅ 5 处补丁全部就位。Next: 重启 dsh-web + 浏览器硬刷新 + 额度查询验证。")
else:
    print("⚠ 存在未就位补丁，运行 ./apply.sh 重放，或参考 patches/ 手工修复。")
    raise SystemExit(1)
PYEOF