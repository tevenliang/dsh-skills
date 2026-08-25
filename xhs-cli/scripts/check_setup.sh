#!/usr/bin/env bash
# xhs-cli skill setup check
# 检查 xhs CLI 是否已安装、登录、版本号
set -e

XHS=~/.local/bin/xhs

echo "🔍 检查 xhs-cli 安装状态"
echo "================================="

# 1. xhs CLI 是否存在
if [ ! -x "$XHS" ]; then
    echo "❌ xhs CLI 未安装"
    echo ""
    echo "安装命令:"
    echo "  uv tool install xiaohongshu-cli"
    echo ""
    echo "安装完后:"
    echo "  xhs login --cookie-source chrome"
    exit 1
fi
echo "✅ xhs CLI 已安装: $XHS"

# 2. 版本
VERSION=$(xhs --version 2>&1)
echo "✅ 版本: $VERSION"

# 3. 登录状态
echo ""
echo "🔐 检查登录状态..."
STATUS=$(xhs status --json 2>&1)
if echo "$STATUS" | grep -q '"ok": true'; then
    NICK=$(xhs whoami --json 2>/dev/null | python3 -c "import sys, json; d = json.loads(sys.stdin.read()); print(d.get('data', {}).get('user', {}).get('nickname', '?'))" 2>/dev/null || echo "?")
    echo "✅ 已登录 (昵称: $NICK)"
else
    echo "❌ 未登录"
    echo ""
    echo "登录步骤:"
    echo "  1. Chrome 中先登录 xiaohongshu.com"
    echo "  2. xhs login --cookie-source chrome"
    exit 1
fi

# 4. Python 依赖
echo ""
echo "🐍 检查 Python 环境..."
if python3 -c "import urllib.request, hashlib" 2>/dev/null; then
    echo "✅ 标准库可用 (urllib, hashlib)"
else
    echo "❌ Python 标准库异常"
fi

# 5. 输出目录
DEFAULT_OUT=~/Documents/agent_spaces/output/xhs_images
if [ -d "$DEFAULT_OUT" ]; then
    echo "✅ 图片输出目录: $DEFAULT_OUT"
else
    echo "ℹ️  创建图片输出目录: $DEFAULT_OUT"
    mkdir -p "$DEFAULT_OUT"
fi

# 6. 试一次搜索(不报错就算 OK)
echo ""
echo "🧪 测试 search 子命令..."
if xhs search "咖啡" --json 2>/dev/null | grep -q '"ok": true'; then
    echo "✅ search 工作正常"
else
    echo "⚠️  search 测试返回异常(可能是网络/IP 问题)"
fi

echo ""
echo "🎉 全部检查完成! 现在可以用:"
echo "  python3 $HOME/.agents/skills/xhs-cli/scripts/xhs_search.py auto '咖啡' --limit 3 --render"
