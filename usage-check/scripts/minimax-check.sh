#!/bin/bash
# MiniMax Coding Plan 用量查询 → JSON 输出
# 端点: https://www.minimaxi.com/v1/api/openplatform/coding_plan/remains
# 字段: current_interval_remaining_percent / current_weekly_remaining_percent
#       model_remains 数组含 general + video（video 始终跳过）
#       status: 1=生效 3=未启用
#
# 从 ~/.agents/credentials/minimax.json 读 API Key

set -u
CRED_FILE="$HOME/.agents/credentials/minimax.json"
SEND_NOTIF="${SEND_NOTIF:-0}"  # 默认不通知（Codex automation 统一发）

python3 - "$CRED_FILE" "$SEND_NOTIF" << 'PYEOF'
import sys, json, subprocess
from datetime import datetime, timezone, timedelta

cred_file = sys.argv[1]
send_notif = sys.argv[2] == "1"

try:
    with open(cred_file) as f:
        api_key = json.load(f).get('api_key', '')
except FileNotFoundError:
    print(json.dumps({"error": "凭证文件不存在: " + cred_file}, ensure_ascii=False))
    sys.exit(1)
except (json.JSONDecodeError, KeyError) as e:
    print(json.dumps({"error": "凭证文件解析失败: " + str(e)}, ensure_ascii=False))
    sys.exit(1)

if not api_key:
    print(json.dumps({"error": "凭证文件缺少 api_key 字段"}, ensure_ascii=False))
    sys.exit(1)

try:
    result = subprocess.run([
        "curl", "-s", "--max-time", "10",
        "-X", "GET",
        "https://www.minimaxi.com/v1/api/openplatform/coding_plan/remains",
        "-H", "Authorization: Bearer " + api_key,
        "-H", "Content-Type: application/json"
    ], capture_output=True, text=True, timeout=15)
    raw = result.stdout
except subprocess.TimeoutExpired:
    print(json.dumps({"error": "API 请求超时"}, ensure_ascii=False))
    sys.exit(1)

if not raw.strip():
    print(json.dumps({"error": "API 返回空响应"}, ensure_ascii=False))
    sys.exit(1)

try:
    data = json.loads(raw)
except json.JSONDecodeError as e:
    print(json.dumps({"error": "JSON 解析失败: " + str(e), "raw_preview": raw[:200]}, ensure_ascii=False))
    sys.exit(1)

if data.get('base_resp', {}).get('status_code') != 0:
    msg = data.get('base_resp', {}).get('status_msg', '未知错误')
    code = data.get('base_resp', {}).get('status_code', '?')
    print(json.dumps({"error": "API 返回错误 [" + str(code) + "]: " + msg}, ensure_ascii=False))
    sys.exit(1)

CST = timezone(timedelta(hours=8))
now_str = datetime.now(tz=CST).strftime('%Y-%m-%d %H:%M:%S')

def fmt_time(ms):
    if not ms:
        return None
    return datetime.fromtimestamp(ms/1000, tz=CST).strftime('%m-%d %H:%M')

def fmt_remain(ms):
    if not ms:
        return None
    sec = ms / 1000
    if sec >= 86400:
        return f'{sec/86400:.1f}天'
    if sec >= 3600:
        return f'{sec/3600:.1f}小时'
    return f'{sec/60:.0f}分钟'

def status_text(s):
    return {1: '生效', 3: '未启用'}.get(s, f'状态{s}')

def health_for(remaining_pct, status):
    """5h 和 weekly 窗口共用阈值"""
    if status == 3:
        return ("未启用", "⚪")
    if remaining_pct < 10:
        return ("紧急", "🚨")
    if remaining_pct < 20:
        return ("紧张", "🔴")
    if remaining_pct < 50:
        return ("正常", "🟡")
    return ("充足", "💚")

models_out = []
general_summary = None  # 用于发 notification

for m in data.get('model_remains', []):
    name = m.get('model_name', '?')
    if name == 'video':
        continue

    pct_5h = m.get('current_interval_remaining_percent', 0)
    pct_w = m.get('current_weekly_remaining_percent', 0)
    st_5h = m.get('current_interval_status', 0)
    st_w = m.get('current_weekly_status', 0)

    h5_text, h5_emoji = health_for(pct_5h, st_5h)
    hw_text, hw_emoji = health_for(pct_w, st_w)
    boost = m.get('weekly_boost_permille', 0) / 100 if m.get('weekly_boost_permille') else 0

    model_data = {
        "model": name,
        "5h_window": {
            "start_time": fmt_time(m.get('start_time', 0)),
            "end_time": fmt_time(m.get('end_time', 0)),
            "remaining_time": fmt_remain(m.get('remains_time', 0)),
            "remaining_time_seconds": int(m['remains_time'] / 1000) if m.get('remains_time') else None,
            "used_percent": 100 - pct_5h,
            "remaining_percent": pct_5h,
            "status": "active" if st_5h == 1 else "inactive",
            "status_text": status_text(st_5h),
            "health": h5_text,
            "health_emoji": h5_emoji
        },
        "weekly_window": {
            "start_time": fmt_time(m.get('weekly_start_time', 0)),
            "end_time": fmt_time(m.get('weekly_end_time', 0)),
            "remaining_time": fmt_remain(m.get('weekly_remains_time', 0)),
            "remaining_time_seconds": int(m['weekly_remains_time'] / 1000) if m.get('weekly_remains_time') else None,
            "used_percent": 100 - pct_w,
            "remaining_percent": pct_w,
            "status": "active" if st_w == 1 else "inactive",
            "status_text": status_text(st_w),
            "boost_percent": boost,
            "health": hw_text,
            "health_emoji": hw_emoji
        }
    }
    models_out.append(model_data)

    if name == 'general':
        general_summary = {
            "rem5": 100 - pct_5h,
            "remw": 100 - pct_w,
            "h5_emoji": h5_emoji,
            "hw_emoji": hw_emoji,
            "h5_text": h5_text,
            "hw_text": hw_text
        }

print(json.dumps({
    "models": models_out,
    "fetched_at": now_str
}, ensure_ascii=False, indent=2))

PYEOF
