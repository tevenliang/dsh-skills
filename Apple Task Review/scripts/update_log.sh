#!/bin/bash
# update_log.sh - 把最近一个月完成的任务追加到 vault 任务完成log.md
# 严格按 completionDate 排, append-only, 保留用户手写的 >> 备注

set -euo pipefail

# 0. 前置检查
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "ERR|此 skill 仅支持 macOS"
    exit 1
fi

CLI="$HOME/.local/bin/reminders-cli"
[ -x "$CLI" ] || { echo "ERR|reminders-cli 不存在: $CLI"; exit 1; }

# vault 路径 (从 memory 拿)
VAULT="${VAULT:-$HOME/Documents/steven_vault}"
[ -d "$VAULT" ] || { echo "ERR|vault 不存在: $VAULT"; exit 1; }

LOG="$VAULT/01_my_notes/任务完成log.md"
LOG_DIR=$(dirname "$LOG")
[ -d "$LOG_DIR" ] || mkdir -p "$LOG_DIR"
[ -f "$LOG" ] || touch "$LOG"

# 1. 解析已有 log, 提取 (date, title) 集合
EXISTING=$(mktemp)
awk '
/^- [0-9]{8}$/ { date=$2; next }
/^[ \t]+- / {
    sub(/^[ \t]+- /, "")
    print date "\t" $0
}
' "$LOG" | sort -u > "$EXISTING"
EXISTING_COUNT=$(wc -l < "$EXISTING" | tr -d ' ')

# 2. 拉最近 30 天
RAW=$("$CLI" done-range 29 0 2>&1) || { echo "ERR|done-range 失败"; exit 1; }
RAW_TOTAL=$(echo "$RAW" | head -1 | awk -F'|' '{print $3}' | awk -F'=' '{print $2}')

# 3. 解析 done-range output, 提取 (date, title)
#    DONE|YYYYMMDD HH:mm|<uuid>|<list>|<title>
#    title 经 sanitize 不会含 |  (含 | 时替换为 /)
NEW=$(mktemp)
echo "$RAW" | awk -F'|' '/^DONE\|/ { split($2,a," "); print a[1] "\t" $5 }' | sort -u > "$NEW"

# 4. diff: new - existing
TO_ADD=$(mktemp)
comm -23 "$NEW" "$EXISTING" > "$TO_ADD"
ADD_COUNT=$(wc -l < "$TO_ADD" | tr -d ' ')

# 5. 合并 existing + to_add, 按 date desc 排序 (台账: 最新在最上)
#    注意: 不论 ADD_COUNT 是否为 0, 都重写整文件以保证 desc 顺序
ALL_PAIRS=$(mktemp)
cat "$EXISTING" "$TO_ADD" | sort -t$'\t' -k1,1 -r > "$ALL_PAIRS"
TOTAL_COUNT=$(wc -l < "$ALL_PAIRS" | tr -d ' ')

# 6. 生成 md
NEW_MD=$(mktemp)
awk -F'\t' '
{
    if ($1 != prev) {
        print "- " $1
        prev = $1
    }
    print "\t- " $2
}' "$ALL_PAIRS" > "$NEW_MD"

# 7. 替换 log (重写整文件, 倒序)
mv "$NEW_MD" "$LOG"

# 8. 报告
echo "OK|scanned=$RAW_TOTAL|existing=$EXISTING_COUNT|added=$ADD_COUNT|total=$TOTAL_COUNT"
echo ""
echo "Rewrote 任务完成log.md with $TOTAL_COUNT entries (sorted by date desc, newest first)"
echo ""
echo "Date breakdown (new entries):"
sort -t$'\t' -k1,1 "$TO_ADD" | cut -f1 | sort | uniq -c | awk '{printf "  %s: +%d\n", $2, $1}'

# cleanup
rm -f "$EXISTING" "$NEW" "$TO_ADD" "$ALL_PAIRS"
