#!/bin/bash
# OpenRouter 余额查询 → JSON 输出
set -u
CRED_FILE="$HOME/.agents/credentials/openrouter.json"
python3 - "$CRED_FILE" << 'PYEOF'
import sys, json, subprocess
from datetime import datetime, timezone, timedelta
cred_file = sys.argv[1]
CST = timezone(timedelta(hours=8))
fetched_at = datetime.now(tz=CST).strftime('%Y-%m-%d %H:%M:%S')
try:
    with open(cred_file) as f:
        data = json.load(f)
        api_key = data.get('api_key', '')
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
        "-X", "GET", "https://openrouter.ai/api/v1/credits",
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
    resp = json.loads(raw)
except json.JSONDecodeError as e:
    print(json.dumps({"error": "JSON 解析失败: " + str(e), "raw_preview": raw[:200]}, ensure_ascii=False))
    sys.exit(1)
inner = resp.get('data', {})
total_credits = inner.get('total_credits', 0)
total_usage   = inner.get('total_usage', 0)
remaining     = round(total_credits - total_usage, 6)
def health_for(x):
    if x >= 50: return ("充足", "💚")
    if x >= 10: return ("正常", "🟡")
    if x >= 1:  return ("偏低", "🔴")
    return ("即将耗尽", "🚨")
h_text, h_emoji = health_for(remaining)
print(json.dumps({
    "total_credits": total_credits,
    "total_usage":   round(total_usage, 6),
    "remaining":     remaining,
    "health":        h_text,
    "health_emoji":  h_emoji,
    "fetched_at":    fetched_at
}, ensure_ascii=False, indent=2))
PYEOF
