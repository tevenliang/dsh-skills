#!/bin/bash
# Tavily API 用量查询 → JSON 输出
# 端点: https://api.tavily.com/usage
#
# 从 ~/.agents/credentials/tavily.json 读 API Key

set -u
CRED_FILE="$HOME/.agents/credentials/tavily.json"

python3 - "$CRED_FILE" << 'PYEOF'
import sys, json, subprocess

cred_file = sys.argv[1]

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
        "curl", "-s", "--max-time", "15",
        "-X", "GET", "https://api.tavily.com/usage",
        "-H", "Authorization: Bearer " + api_key
    ], capture_output=True, text=True, timeout=20)
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

account = data.get('account', {})
usage = account.get('plan_usage')
limit = account.get('plan_limit')

if usage is None or limit is None:
    print(json.dumps({"error": "字段缺失 (plan_usage / plan_limit)", "raw_preview": raw[:200]}, ensure_ascii=False))
    sys.exit(1)

remaining = limit - usage
pct = round(usage / limit * 100, 1) if limit > 0 else 0

# 健康度阈值（基于已用百分比，跟 DeepSeek 思路对齐）
def health_for(used_pct):
    if used_pct >= 90:
        return ("紧急", "🚨")
    if used_pct >= 75:
        return ("紧张", "🔴")
    if used_pct >= 50:
        return ("正常", "🟡")
    return ("充足", "💚")

h_text, h_emoji = health_for(pct)

from datetime import datetime, timezone, timedelta
CST = timezone(timedelta(hours=8))
fetched_at = datetime.now(tz=CST).strftime('%Y-%m-%d %H:%M:%S')

print(json.dumps({
    "plan": account.get('current_plan', 'unknown'),
    "limit": limit,
    "used": usage,
    "used_percent": pct,
    "remaining": remaining,
    "search_usage": account.get('search_usage', 0),
    "health": h_text,
    "health_emoji": h_emoji,
    "fetched_at": fetched_at
}, ensure_ascii=False, indent=2))
PYEOF
