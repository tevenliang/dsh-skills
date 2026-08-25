#!/bin/bash
# WPS 云文档 → Claude Code 接入脚本
# 使用方式: bash ~/.agents/skills/kdocs/setup-wps.sh

set -euo pipefail

SETTINGS_FILE="$HOME/.claude/settings.json"
MCP_URL="https://mcp-center.wps.cn/skill_hub/mcp"
SKILL_VERSION="1.3.3"

gen_uuid() { uuidgen | tr 'A-Z' 'a-z'; }
urlencode() { python3 -c "import urllib.parse; import sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$1"; }
get_json_val() { python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('data',d).get('$1','') or '')" 2>/dev/null || true; }

echo ""
echo "============================================"
echo "  WPS 云文档 · Claude Code 接入"
echo "============================================"
echo ""

CODE=$(gen_uuid)
CB="https://api.wps.cn/office/v5/ai/skill_hub/users/callback?code=${CODE}"
ENCODED_CB=$(urlencode "$CB")
LOGIN_URL="https://account.wps.cn/login?cb=${ENCODED_CB}"

echo "📋 请复制下面链接到浏览器中打开并登录 WPS："
echo ""
echo "   ${LOGIN_URL}"
echo ""
echo "⚠️  登录完成后浏览器会跳转到空白页，这是正常的，不用管它。"
echo "⏳ 本脚本会自动检测登录状态并完成配置。"
echo ""

# 删掉旧的错误配置（如果有）
python3 -c "
import json, os
sp = os.path.expanduser('$SETTINGS_FILE')
if os.path.exists(sp):
    with open(sp) as f: c = json.load(f)
    c.get('mcpServers', {}).pop('kdocs', None)
    with open(sp, 'w') as f: json.dump(c, f, indent=2, ensure_ascii=False)
    print('已清理旧配置')
"

TIMEOUT=600
INTERVAL=2
START=$(date +%s)
DOTS=0

while true; do
  NOW=$(date +%s)
  ELAPSED=$((NOW - START))
  if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
    echo ""
    echo "❌ 登录超时（${TIMEOUT}秒），请重试"
    exit 1
  fi

  RESPONSE=$(curl -s -X POST \
    "https://api.wps.cn/office/v5/ai/skill_hub/wps_auth/exchange" \
    -H "Content-Type: application/json" \
    -d "{\"code\": \"${CODE}\"}")

  RESP_CODE=$(echo "$RESPONSE" | get_json_val "code")
  TOKEN=$(echo "$RESPONSE" | get_json_val "token")
  EXPIRES=$(echo "$RESPONSE" | get_json_val "expires_in")

  if [ "$RESP_CODE" = "200" ] && [ -n "$TOKEN" ]; then
    echo ""
    echo ""
    echo "✅ WPS 登录成功！"

    EXPIRES_HOURS=$((EXPIRES / 3600))
    echo "⏰ Token 有效期: 约 ${EXPIRES_HOURS} 小时"

    # 写入 settings.json
    python3 <<-PY
import json, os
sp = os.path.expanduser("$SETTINGS_FILE")
token = "$TOKEN"
if os.path.exists(sp):
    with open(sp) as f: config = json.load(f)
else:
    config = {}
config.setdefault('mcpServers', {})
config['mcpServers']['kdocs'] = {
    "type": "url",
    "url": "$MCP_URL",
    "headers": {
        "Authorization": f"Bearer {token}",
        "X-Skill-Version": "$SKILL_VERSION",
        "X-Request-Source": "claude-code"
    }
}
with open(sp, 'w') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
print("✅ 配置已写入 settings.json")
PY

    echo ""
    echo "🎉 WPS 云文档接入完成！现在你可以让我直接操作 WPS 云文档了。"
    echo "试试说："
    echo "  - \"看看我 WPS 云盘上有什么文件\""
    echo "  - \"在 WPS 上新建一个文档\""
    exit 0

  elif [ "$RESP_CODE" = "202" ]; then
    DOTS=$((DOTS + 1))
    [ $((DOTS % 10)) -eq 0 ] && printf "."
  fi

  sleep "$INTERVAL"
done
