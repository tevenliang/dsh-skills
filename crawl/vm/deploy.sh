#!/bin/bash
# deploy.sh — 把本地 crawl/vm/ 的源码部署到 VM 并重启两个 daemon
#
# 用法（在 Mac 本地执行）:
#   bash ~/.agents/skills/crawl/vm/deploy.sh
#
# 前置:
#   - ssh 别名 `vm` 已在 ~/.ssh/config 配好（含 IdentityFile）
#   - VM 上 /home/ubuntu/crawl-transcribe/ 已存在，且 venv 就绪
#
# 设计原则:
#   - crawl/vm/ 是 VM 运行目录 (crawl-transcribe/) 的 1:1 源码镜像，git 追踪
#   - 部署 = rsync 源码 + 重启进程；运行期数据（done/inbox/ocr_inbox/status.jsonl/models）留在 VM，不纳入本仓库
#   - 重启用 pkill -f '[_]' 防御自杀，setsid nohup 拉起，与原有 restart_daemon.sh 一致

set -euo pipefail

VM_HOST="vm"
VM_DIR="/home/ubuntu/crawl-transcribe"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> [1/3] rsync 源码 crawl/vm/*.py -> ${VM_HOST}:${VM_DIR}"
rsync -avz --delete \
  --exclude='*.bak*' \
  --exclude='__pycache__' \
  --exclude='.DS_Store' \
  --exclude='gen_vm_publish.py' \
  "${SRC_DIR}/"*.py \
  "${VM_HOST}:${VM_DIR}/"

restart_daemon() {
  # $1 = 进程匹配模式（用 [_] 防御 pkill 自杀）, $2 = 启动命令, $3 = 日志
  local pat="$1" launch="$2" log="$3"
  echo "==> 重启 daemon: ${pat}"
  # 注意: pkill 后必须 || true, 否则 set -e 会在「无匹配进程」时提前退出脚本,
  # 导致后续 daemon 不被重启(本次 8/22 踩坑: ocr 因 transcribe pkill 返回码问题漏重启).
  # setsid 直接拉起(不套 bash -c 包装), 新会话脱离 SSH 会话, 断开后不丢进程.
  ssh "${VM_HOST}" "pkill -f '${pat}' 2>/dev/null || true; sleep 2; cd ${VM_DIR}; setsid ${launch} > ${log} 2>&1 < /dev/null &"
}

echo "==> [2/3] 重启 transcribe_daemon"
restart_daemon 'transcribe[_]daemon\.py' 'venv/bin/python transcribe_daemon.py' '/tmp/daemon.log'

echo "==> [3/3] 重启 ocr_daemon"
restart_daemon 'ocr[_]daemon\.py' 'venv/bin/python ocr_daemon.py' '/tmp/ocr_daemon.log'

echo "==> 等待进程就绪..."
sleep 6

echo "==> 验证 VM 进程"
ssh "${VM_HOST}" "ps -eo pid,etimes,cmd | grep -E 'transcribe_daemon|ocr_daemon' | grep -v grep"

echo "==> 部署完成。如需回滚: git checkout <commit> crawl/vm/ && bash deploy.sh"
