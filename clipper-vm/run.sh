#!/bin/bash
# clipper-vm 入口 — 单条/剪藏链路 (独立于 crawl-vm)
# 用法: ./run.sh [--dry-run] [--limit N] [--url <url>]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" >/dev/null 2>&1 && pwd)"
SKILL_DIR="$SCRIPT_DIR"

# Python 路径 (复用 crawl-vm venv — 含 xhs-cli/httpx/gmssl/trafilatura/bs4)
if [ -x "/home/ubuntu/.dsh/skills/crawl-vm/.venv/bin/python3" ]; then
    PYTHON="/home/ubuntu/.dsh/skills/crawl-vm/.venv/bin/python3"
elif [ -x "/home/ubuntu/.dsh/.venv/bin/python3" ]; then
    PYTHON="/home/ubuntu/.dsh/.venv/bin/python3"
elif [ -x "/usr/bin/python3" ]; then
    PYTHON="/usr/bin/python3"
else
    echo "❌ 找不到可用 Python" >&2; exit 1
fi

# 显式指定 SSL 证书 (VPN 代理 HTTPS 需要正确 CA)
export SSL_CERT_FILE="/etc/ssl/certs/ca-certificates.crt"
export SSL_CERT_DIR="/etc/ssl/certs"

cd "$SKILL_DIR"
exec $PYTHON -m clip "$@"