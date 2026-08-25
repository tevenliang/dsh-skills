#!/bin/zsh
# ominicrawl 唯一入口
# 全流程：watchlist → clip → report（统一一个 supervisor session）
# 
# 设计原则（2026-07-30 v2）：
# - run.sh 是唯一入口，不再分散在 supervisor.py / crawl.py
# - 内部调用 supervisor.py --all，自动串接 watchlist/clip/report
# - 每次跑批生成 run_<tag>，所有 state/log 按 tag 拆分
# - OP 报告从 events.jsonl 读，fallback 到 log parse

SCRIPT_DIR="$(cd "$(dirname "$0")" >/dev/null 2>&1 && pwd)"
SKILL="$SCRIPT_DIR"
source "$SKILL/../common/py.sh" 2>/dev/null

# ── PATH + 资源限制（launchd daemon 启动时也必须带）────────────
# launchd 启动的子进程 PATH 只有 /usr/bin:/bin:/usr/sbin:/sbin，
# 找不到 npm-global 里的 bl / bailian CLI，导致 check_bailian_quota.py
# 里 shutil.which("bl") 返回 None → _query_one() 抛 TypeError。
export PATH="$HOME/.npm-global/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

# CRAWL_NOTIFY 已废弃 (2026-07-30 v2): 删了 plist, 删了 osascript 通知, 留作 no-op
# export CRAWL_NOTIFY=0


# 提高文件句柄上限，xhs 子进程 fork + macOS Resource temporarily unavailable 需要
ulimit -n 10240 2>/dev/null || true

# supervisor 使用了 Python 3.10+ 语法；自动任务环境不能误退回 macOS 自带的 3.9。
_python_ok() {
    [ -n "$1" ] && [ -x "$1" ] && "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

# 优先系统级 venv；不存在或版本太旧时，依次使用 py.sh 已选版本和 Homebrew Python。
_venv="$SKILL/../../.venv/bin/python3"
if _python_ok "$_venv"; then
    PY="$_venv"
elif ! _python_ok "$PY"; then
    PY=""
    for _candidate in /opt/homebrew/bin/python3 "$HOME/.local/bin/python3.12"; do
        if _python_ok "$_candidate"; then
            PY="$_candidate"
            break
        fi
    done
fi

if ! _python_ok "$PY"; then
    echo "❌ crawl 需要 Python 3.10 或更高版本，当前没有找到可用版本。" >&2
    exit 2
fi

# ── 凭证注入（从 credential 文件读取，不再硬编码）─────────────
_XFYUN_CREDS="$HOME/.agents/credentials/ominicrawl/xfyun.json"
if [[ -f "$_XFYUN_CREDS" ]]; then
    # 读取 JSON 凭证（需 Python 解析）
    _xf_appid=$($PY -c "import json; print(json.load(open('$_XFYUN_CREDS'))['appid'])" 2>/dev/null)
    _xf_apikey=$($PY -c "import json; print(json.load(open('$_XFYUN_CREDS'))['apikey'])" 2>/dev/null)
    _xf_apisecret=$($PY -c "import json; print(json.load(open('$_XFYUN_CREDS'))['apisecret'])" 2>/dev/null)
    if [[ -n "$_xf_appid" ]]; then
        export XFYUN_APPID="$_xf_appid"
        export XFYUN_APIKEY="$_xf_apikey"
        export XFYUN_APISECRET="$_xf_apisecret"
        echo "[run.sh] XFYUN 凭证已从 $_XFYUN_CREDS 加载"
    else
        echo "[run.sh] ⚠️ XFYUN 凭证文件格式错误，XFYUN 相关功能可能不可用" >&2
    fi
else
    echo "[run.sh] ⚠️ XFYUN 凭证文件不存在: $_XFYUN_CREDS，XFYUN 相关功能可能不可用" >&2
fi

# ── 参数解析 ──────────────────────────────────────────────
DATE=$(date +%Y%m%d)
CMD=${1:-all}
shift || true

while [[ $# -gt 0 ]]; do
    case $1 in
        --date)
            DATE="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

# ── 唯一运行入口 ──────────────────────────────────────────────
case $CMD in
  all)
    # 一气呵成：watchlist → clip → report（全在一个 supervisor session 里）
    # 2026-07-30 v2: 日志名改 run_<DATE>_<HHMMSS>.out (旧 launchd_*.out 仍保留作历史)
    _TS=$(date +%H%M%S)
    _LOG="$SKILL/logs/run_${DATE}_${_TS}.out"
    mkdir -p "$(dirname "$_LOG")"
    echo "🚀 ominicrawl 统一入口: all $DATE"
    export CRAWL_LOG_PATH="$_LOG"
    $PY -u "$SKILL/common_supervisor/supervisor.py" \
        --all "$DATE" \
        --py "$PY" \
        --skill "$SKILL" \
        2>&1 | tee "$_LOG"
    _rc=${PIPESTATUS[0]}
    exit $_rc
    ;;
  status)
    $PY -u "$SKILL/common_supervisor/supervisor.py" --status
    ;;
  reset)
    $PY -u "$SKILL/common_supervisor/supervisor.py" --reset
    ;;
  report)
    # 2026-07-30 v2: 优先读 run_<tag>.events.jsonl, 找不到再 fallback log parse
    # (具体逻辑在 report_timing._resolve_data())
    "$PY" "$SKILL/report_timing.py" --date "$DATE"
    ;;
  help|*)
    cat <<HELP
ominicrawl 统一入口 (2026-07-27 重构)

用法: ./run.sh <命令> [选项]

命令:
  all [日期]    🚀 全流程一气呵成：watchlist → clip → report（推荐）
  status        查看 supervisor 状态
  report        从最后一次跑批日志生成 OP 报告
  reset         重置 supervisor 状态
  help          显示帮助

选项:
  --date YYYYMMDD    指定日期（默认今天）

示例:
  ./run.sh all                    # 跑今天的全流程
  ./run.sh all --date 20260727    # 跑指定日期
  ./run.sh report --date 20260729 # 重建指定日期最后一次跑批的 OP 报告
HELP
    ;;
esac
