#!/bin/bash
# 基金估值图片生成脚本（移除 OpenClaw 依赖）
# 使用方式: ./fund_generate_image.sh

set -e

FUNDS=("013273" "004070" "024618" "007883" "013172" "006195" "024003" "021458" "012414" "018561" "014415")
LOG_DIR="${HOME}/.fund_reports/logs"
OUTPUT_DIR="${HOME}/.fund_reports/screenshots"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 创建目录
mkdir -p "$LOG_DIR" "$OUTPUT_DIR"

LOG_FILE="$LOG_DIR/fund_generate_$(date '+%Y%m%d').log"

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

# 复制到输出目录
cp "$PNG_PATH" "$OUTPUT_DIR/latest.png"
cp "$PNG_PATH" "$OUTPUT_DIR/fund_report_$(date '+%Y%m%d_%H%M%S').png"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 图片已保存到输出目录" | tee -a "$LOG_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 生成完成" | tee -a "$LOG_FILE"

# 输出图片路径供后续使用
echo "FUND_IMAGE_PATH=$PNG_PATH" >> "$GITHUB_OUTPUT" 2>/dev/null || true
echo "$PNG_PATH"