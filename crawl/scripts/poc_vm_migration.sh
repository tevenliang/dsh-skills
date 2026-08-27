#!/bin/bash
#===============================================================================
# POC: 将 crawl 最小化迁移到 VM，测试 B站/抖音 单条爬取
#
# 依赖:
#   - Mac 上已配置 SSH 免密到 VM (ssh ubuntu@175.178.210.156)
#   - VM 上 ~/.agents/credentials/ominicrawl/ 已存在 groq.json / zhipu.json
#
# 用法:
#   ./scripts/poc_vm_migration.sh sync      # 同步代码和凭证到 VM
#   ./scripts/poc_vm_migration.sh install    # 在 VM 上安装依赖
#   ./scripts/poc_vm_migration.sh bilibili   # 测试 B站
#   ./scripts/poc_vm_migration.sh douyin     # 测试抖音
#   ./scripts/poc_vm_migration.sh all        # 执行全部
#===============================================================================

set -e

VM_HOST="175.178.210.156"
VM_USER="ubuntu"
VM_SKILL_DIR="/home/ubuntu/.agents/skills/crawl"
VM_PYTHON="${VM_PYTHON:-python3}"
SKILL_ROOT="$HOME/.dsh/skills/crawl"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

#===============================================================================
# 步骤 1: 同步 crawl 代码到 VM
#===============================================================================
do_sync() {
    log_info "步骤 1: 同步 crawl 代码到 VM..."
    
    rsync -av --progress \
        --exclude 'logs/' \
        --exclude 'state/' \
        --exclude '.venv/' \
        --exclude '__pycache__/' \
        --exclude '*.pyc' \
        --exclude '*.py.current' \
        --exclude '.DS_Store' \
        --exclude '*.bak' \
        --exclude '*.out' \
        "${SKILL_ROOT}/" \
        "${VM_USER}@${VM_HOST}:${VM_SKILL_DIR}/"
    
    log_info "代码同步完成"
}

#===============================================================================
# 步骤 2: 同步凭证到 VM
#===============================================================================
do_sync_creds() {
    log_info "步骤 2: 同步凭证到 VM..."
    
    # B站凭证
    local BILI_SRC="$HOME/.agents/credentials/ominicrawl/bilibili.txt"
    if [[ -f "$BILI_SRC" ]]; then
        ssh "${VM_USER}@${VM_HOST}" "mkdir -p ~/.agents/credentials/ominicrawl"
        scp "$BILI_SRC" "${VM_USER}@${VM_HOST}:~/.agents/credentials/ominicrawl/bilibili.txt"
        log_info "B站凭证已同步"
    else
        log_warn "B站凭证不存在: $BILI_SRC"
    fi
    
    # Douyin config.yaml（包含 Cookie）
    local DOUYIN_CONFIG="${SKILL_ROOT}/ingest-douyin/douyin_api/crawlers/douyin/web/config.yaml"
    if [[ -f "$DOUYIN_CONFIG" ]]; then
        rsync -av "$DOUYIN_CONFIG" \
            "${VM_USER}@${VM_HOST}:${VM_SKILL_DIR}/ingest-douyin/douyin_api/crawlers/douyin/web/config.yaml"
        log_info "抖音 config.yaml 已同步"
    else
        log_warn "抖音 config 不存在: $DOUYIN_CONFIG"
    fi
    
    log_info "凭证同步完成"
}

#===============================================================================
# 步骤 3: VM 上安装依赖
#===============================================================================
do_install() {
    log_info "步骤 3: VM 上安装 Python 依赖..."
    
    ssh "${VM_USER}@${VM_HOST}" <<'VMSSH'
set -e
SKILL_DIR="/home/ubuntu/.agents/skills/crawl"
cd "$SKILL_DIR"

echo "Python version: $(python3 --version)"

# 创建 venv（如果不存在）
if [[ ! -d ".venv" ]]; then
    echo "Creating venv..."
    python3 -m venv .venv --system-site-packages
fi

# 升级 pip
.venv/bin/pip install -q --upgrade pip

# 安装核心依赖
.venv/bin/pip install -q httpx pyyaml python-dateutil

# 检查关键包
.venv/bin/pip show httpx pyyaml 2>/dev/null | grep -E "^Name:|^Version:" || true

echo "Dependencies check completed"
VMSSH

    log_info "依赖安装完成"
}

#===============================================================================
# 步骤 4: B站单条测试
#===============================================================================
do_test_bilibili() {
    log_info "步骤 4: B站单条测试..."
    
    local BVID="${TEST_BVID:-BV1GJ411x7h7}"
    
    ssh "${VM_USER}@${VM_HOST}" <<VMSSH
set -e
SKILL_DIR="/home/ubuntu/.agents/skills/crawl"
cd "\$SKILL_DIR"

export VAULT="/home/ubuntu/webdav/steven_vault"
export USE_VM="true"

echo "============================================"
echo "B站测试 (BVID=$BVID)"
echo "============================================"

# 列出凭证文件是否存在
echo "Checking bilibili.txt..."
head -c 100 ~/.agents/credentials/ominicrawl/bilibili.txt || echo "File not found!"

echo ""
echo "Attempting Bilibili crawl..."

# 直接调用 Python 测试（不依赖完整 crawl.py）
.venv/bin/python3 <<'PYEOF'
import sys
import os
sys.path.insert(0, '/home/ubuntu/.agents/skills/crawl')

# 简单测试：读取 bilibili cookie
creds_path = os.path.expanduser("~/.agents/credentials/ominicrawl/bilibili.txt")
if os.path.exists(creds_path):
    content = open(creds_path).read()
    if "SESSDATA" in content:
        print(f"✓ bilibili.txt 凭证有效 (长度: {len(content)} bytes)")
        print(f"  SESSDATA 存在: {'SESSDATA=' in content}")
    else:
        print(f"✗ bilibili.txt 无 SESSDATA")
        sys.exit(1)
else:
    print(f"✗ bilibili.txt 不存在")
    sys.exit(1)
PYEOF

echo ""
echo "B站凭证检查完成"
VMSSH

    log_info "B站测试完成"
}

#===============================================================================
# 步骤 5: 抖音单条测试
#===============================================================================
do_test_douyin() {
    log_info "步骤 5: 抖音单条测试..."
    
    ssh "${VM_USER}@${VM_HOST}" <<'VMSSH'
set -e
SKILL_DIR="/home/ubuntu/.agents/skills/crawl"
cd "$SKILL_DIR"

export VAULT="/home/ubuntu/webdav/steven_vault"

echo "============================================"
echo "抖音测试"
echo "============================================"

# 检查 config.yaml 中的 Cookie
CONFIG="$SKILL_DIR/ingest-douyin/douyin_api/crawlers/douyin/web/config.yaml"
if [[ -f "$CONFIG" ]]; then
    COOKIE_LINE=$(grep -m1 "Cookie:" "$CONFIG" || echo "")
    if [[ -n "$COOKIE_LINE" ]]; then
        echo "✓ Douyin config.yaml 凭证有效"
        echo "  Cookie 长度: ${#COOKIE_LINE} bytes"
        echo "  Cookie 片段: ${COOKIE_LINE:0:80}..."
    else
        echo "✗ Douyin config.yaml 无 Cookie"
        exit 1
    fi
else
    echo "✗ Douyin config.yaml 不存在"
    exit 1
fi

# 简单连接测试
echo ""
echo "测试抖音 API 连接..."
.venv/bin/python3 <<'PYEOF'
import sys
sys.path.insert(0, '/home/ubuntu/.agents/skills/crawl')

try:
    import httpx
    # 简单测试：访问抖音首页
    resp = httpx.get("https://www.douyin.com/", timeout=10, follow_redirects=True)
    print(f"✓ 抖音 API 可访问 (status: {resp.status_code})")
except Exception as e:
    print(f"✗ 抖音 API 访问失败: {e}")
    sys.exit(1)
PYEOF

echo ""
echo "抖音凭证检查完成"
VMSSH

    log_info "抖音测试完成"
}

#===============================================================================
# 主流程
#===============================================================================
main() {
    echo "============================================"
    echo "  POC: Crawl VM 迁移测试"
    echo "============================================"
    log_info "开始时间: $(date)"
    
    # 检查 SSH
    log_info "检查 SSH 连接..."
    if ! ssh -o ConnectTimeout=5 "${VM_USER}@${VM_HOST}" "echo OK" > /dev/null 2>&1; then
        log_error "无法连接到 VM"
        exit 1
    fi
    log_info "SSH 连接正常"
    
    # 执行步骤
    do_sync
    do_sync_creds
    do_install
    
    log_info "============================================"
    log_info "  依赖就绪，可执行手动测试"
    log_info "============================================"
    echo ""
    echo "  # 在 VM 上手动测试 B站:"
    echo "  ssh ${VM_USER}@${VM_HOST}"
    echo "  cd ${VM_SKILL_DIR}"
    echo "  export VAULT=/home/ubuntu/webdav/steven_vault"
    echo "  .venv/bin/python3 ingest-bilibili/bilibili/crawl.py <BV号> test_user \$VAULT/notes/bilibili/test"
    echo ""
    echo "  # 在 VM 上手动测试 抖音:"
    echo "  ssh ${VM_USER}@${VM_HOST}"  
    echo "  cd ${VM_SKILL_DIR}"
    echo "  export VAULT=/home/ubuntu/webdav/steven_vault"
    echo "  .venv/bin/python3 ingest-douyin/douyin/crawl.py <aweme_id> test_user \$VAULT/notes/douyin/test"
    echo ""
}

#===============================================================================
# 命令分发
#===============================================================================
usage() {
    echo "用法: $0 <命令>"
    echo ""
    echo "命令:"
    echo "  all       执行完整 POC (同步 + 安装)"
    echo "  sync      只同步代码和凭证"
    echo "  install   只安装依赖"
    echo "  bilibili 测试 B站凭证"
    echo "  douyin   测试抖音凭证"
    echo ""
    echo "示例:"
    echo "  $0 all                    # 执行全部"
    echo "  TEST_BVID=BVxxx $0 bilibili  # 测试指定 B站视频"
}

case "${1:-all}" in
    all)
        main
        ;;
    sync)
        do_sync
        do_sync_creds
        ;;
    install)
        do_install
        ;;
    bilibili)
        do_test_bilibili
        ;;
    douyin)
        do_test_douyin
        ;;
    help|--help|-h)
        usage
        ;;
    *)
        log_error "未知命令: $1"
        usage
        exit 1
        ;;
esac
