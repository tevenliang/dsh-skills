#!/bin/bash
# crawl-vm 入口脚本
# 用法: ./run.sh [douyin|bilibili|xiaohongshu|all] [选项]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" >/dev/null 2>&1 && pwd)"
SKILL_DIR="$SCRIPT_DIR"

# Python 路径（优先用 crawl-vm 自带 venv，含 xhshow/curl_cffi）
if [ -x "/home/ubuntu/.dsh/skills/crawl-vm/.venv/bin/python3" ]; then
    PYTHON="/home/ubuntu/.dsh/skills/crawl-vm/.venv/bin/python3"
elif [ -x "/home/ubuntu/.dsh/.venv/bin/python3" ]; then
    PYTHON="/home/ubuntu/.dsh/.venv/bin/python3"
elif [ -x "/usr/bin/python3" ]; then
    PYTHON="/usr/bin/python3"
else
    echo "❌ 找不到可用 Python" >&2; exit 1
fi

# 显式指定 SSL 证书文件，防止 certifi.where() 在某些环境下返回无效路径
# （特别重要：通过 VPN 代理访问 HTTPS 时 httpx 需要正确的 CA bundle）
export SSL_CERT_FILE="/etc/ssl/certs/ca-certificates.crt"
export SSL_CERT_DIR="/etc/ssl/certs"

# 默认参数
PLATFORMS="all"
DATE=$(date +%Y%m%d)

# 解析参数
CMD=${1:-all}
shift || true

while [[ $# -gt 0 ]]; do
    case $1 in
        --date)
            DATE="$2"
            shift 2
            ;;
        --douyin-ids)
            DOUYIN_IDS="${*:2}"
            shift $#
            ;;
        --bilibili-ids)
            BILIBILI_IDS="${*:2}"
            shift $#
            ;;
        --douyin-authors)
            DOUYIN_AUTHORS="${*:2}"
            shift $#
            ;;
        --bilibili-authors)
            BILIBILI_AUTHORS="${*:2}"
            shift $#
            ;;
        --xiaohongshu-authors)
            XIAOHONGSHU_AUTHORS="${*:2}"
            shift $#
            ;;
        --xiaohongshu-ids)
            XIAOHONGSHU_IDS="${*:2}"
            shift $#
            ;;
        *)
            shift
            ;;
    esac
done

case $CMD in
  douyin)
    PLATFORMS="douyin"
    ;;
  bilibili)
    PLATFORMS="bilibili"
    ;;
  xiaohongshu)
    PLATFORMS="xiaohongshu"
    ;;
  xhs)
    PLATFORMS="xiaohongshu"
    ;;
  all)
    PLATFORMS="all"
    ;;
  help|--help|-h)
    echo "crawl-vm (完全运行在 VM 上)"
    echo ""
    echo "用法: ./run.sh <命令> [选项]"
    echo ""
    echo "命令:"
    echo "  douyin       只爬取抖音"
    echo "  bilibili     只爬取 B站"
    echo "  xiaohongshu  只爬取小红书 (别名 xhs)"
    echo "  all          爬取所有平台 (默认)"
    echo ""
    echo "选项:"
    echo "  --date YYYYMMDD              指定日期"
    echo "  --douyin-ids ID [ID...]      指定抖音视频 ID"
    echo "  --bilibili-ids ID [ID...]    指定 B站视频 BV 号"
    echo "  --douyin-authors ID [ID...]  指定抖音博主 sec_uid"
    echo "  --bilibili-authors ID [ID...] 指定 B站博主 mid"
    echo "  --xiaohongshu-authors ID [ID...] 指定小红书博主 user_id"
    echo ""
    echo "示例:"
    echo "  ./run.sh all                          # 爬取所有平台的 watchlist"
    echo "  ./run.sh douyin --douyin-ids 7673836885130661158"
    echo "  ./run.sh bilibili --bilibili-ids BV1xx411c7mu"
    echo "  ./run.sh xiaohongshu --xiaohongshu-authors 5f92b728..."
    exit 0
    ;;
esac

# 构建命令
CMD_ARGS="--platforms $PLATFORMS --date $DATE"

if [[ -n "$DOUYIN_IDS" ]]; then
    CMD_ARGS="$CMD_ARGS --douyin-ids $DOUYIN_IDS"
fi

if [[ -n "$BILIBILI_IDS" ]]; then
    CMD_ARGS="$CMD_ARGS --bilibili-ids $BILIBILI_IDS"
fi

if [[ -n "$DOUYIN_AUTHORS" ]]; then
    CMD_ARGS="$CMD_ARGS --douyin-authors $DOUYIN_AUTHORS"
fi

if [[ -n "$BILIBILI_AUTHORS" ]]; then
    CMD_ARGS="$CMD_ARGS --bilibili-authors $BILIBILI_AUTHORS"
fi

if [[ -n "$XIAOHONGSHU_AUTHORS" ]]; then
    CMD_ARGS="$CMD_ARGS --xiaohongshu-authors $XIAOHONGSHU_AUTHORS"
fi

if [[ -n "$XIAOHONGSHU_IDS" ]]; then
    CMD_ARGS="$CMD_ARGS --xiaohongshu-ids $XIAOHONGSHU_IDS"
fi

echo "🚀 crawl-vm 启动 (supervised)"
echo "  platforms: $PLATFORMS"
echo "  date: $DATE"

# 运行（走 supervisor 守护: ActionMonitor 监控 active item 卡死并自动 kill,
#       实时解析 stdout, 维护 state/supervisor.json 供轮询）
cd "$SKILL_DIR"
$PYTHON -m common_supervisor.supervisor --sub $PYTHON -m pipeline.run $CMD_ARGS
