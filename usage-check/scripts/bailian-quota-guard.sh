#!/bin/bash
# bailian-quota-guard.sh → 转发到同目录 Python 脚本
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
exec python3 "$SCRIPT_DIR/bailian-quota-guard.py" "$@"
