#!/usr/bin/env bash
# fetch_inbox_links.sh - 从 03_daily/*.md 提取链接，批量抓取到 inbox
# 触发词: 抓日记
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

# 03_daily 是用户日记(源链接), 统一落在 project_crawl/daily
DAILY_DIR="${DAILY_DIR:-$(python3 -c "import sys;sys.path.insert(0,'$SCRIPT_DIR');import paths;print(paths.daily_dir())" 2>/dev/null || echo "/Users/tianwenliang/.agents/skills/ominicrawl/daily")}"

# 用 Python 提取所有 URL，按平台过滤后去重
export DAILY_DIR
mapfile -t URLS < <(
  python3 << 'PYEOF'
import re, os, sys

# 支持的平台域名
PLATFORMS = [
    'bilibili.com', 'b23.tv',
    'xiaohongshu.com', 'xhslink.com',
    'douyin.com', 'iesdouyin.com',
    'mp.weixin.qq.com',
]

daily_dir = os.environ.get('DAILY_DIR', '')
seen = set()
for fname in sorted(os.listdir(daily_dir)):
    if not fname.endswith('.md'):
        continue
    text = open(os.path.join(daily_dir, fname), errors='ignore').read()
    urls = re.findall(r'https?://\S+', text)
    for u in urls:
        clean = re.sub(r'[)\],;<>\s].*$', '', u).strip()
        base = clean.split('?')[0]
        if not base or base in seen:
            continue
        # 过滤支持平台
        if any(p in base for p in PLATFORMS):
            seen.add(base)
            print(base)
PYEOF
)

echo "=== 从 03_daily/ 发现 ${#URLS[@]} 条链接 ==="

if [ ${#URLS[@]} -eq 0 ]; then
  echo "没有链接，退出"
  exit 0
fi

echo "开始抓取..."
success=0
fail=0
for url in "${URLS[@]}"; do
  echo "--- $url"
  result=$(bash "$SCRIPT_DIR/fetch_url.sh" "$url" --inbox 2>&1)
  echo "$result"
  if echo "$result" | grep -q "BLOGGER_OK"; then
    ((success++))
  else
    ((fail++))
  fi
  sleep 2
done

echo ""
echo "=== 完成: 成功 $success，失败 $fail ==="
echo "VM subscription-expert daemon 会在后台自动处理转录/总结"
