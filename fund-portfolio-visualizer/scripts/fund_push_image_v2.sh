#!/bin/bash
# 基金估值图片推送脚本
# 使用方式: ./fund_push_image_v2.sh

set -e

FUNDS=("013273" "004070" "024618" "007883" "013172" "006195" "024003" "021458" "012414" "018561")
CHAT_ID="oc_0145d62d7653a3535bf989104c9268c8"
LOG_FILE="/root/.openclaw/workspace/logs/fund_push_image.log"
SCRIPT_DIR="/root/.openclaw/workspace/skills/valuation-of-funds-skill/scripts"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 开始生成基金估值图..." | tee -a "$LOG_FILE"

# 运行 Node.js 脚本生成图片
OUTPUT=$(cd "$SCRIPT_DIR" && node fund_image_playwright.js 2>&1)
echo "$OUTPUT" | tee -a "$LOG_FILE"

# 提取图片路径
PNG_PATH=$(echo "$OUTPUT" | grep "图片已保存:" | sed 's/图片已保存: //' | tr -d '\r')

if [ -z "$PNG_PATH" ] || [ ! -f "$PNG_PATH" ]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] 错误: 图片生成失败" | tee -a "$LOG_FILE"
  exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 图片生成成功: $PNG_PATH" | tee -a "$LOG_FILE"

# 发送到飞书
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 正在发送到飞书..." | tee -a "$LOG_FILE"
openclaw message send --channel feishu --target "$CHAT_ID" --media "$PNG_PATH" 2>&1 | tee -a "$LOG_FILE"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 推送完成" | tee -a "$LOG_FILE"
