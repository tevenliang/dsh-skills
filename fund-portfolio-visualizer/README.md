---
name: fund-portfolio-visualizer
description: 基金池实时估值可视化工具。获取基金实时估值数据，生成美观的图片报告。支持自定义基金代码列表、自动计算平均涨跌幅、使用 Playwright 生成高质量 PNG 图片。支持通过 Hermes cronjob 定时推送到微信。
---

# Fund Portfolio Visualizer

基金池实时估值可视化工具，生成美观的图片报告。

## 功能

1. **实时数据获取** - 从天天基金网获取基金实时估值数据
2. **图片生成** - 使用 Playwright 生成美观的 PNG 报告
3. **自定义配置** - 支持自定义基金代码列表
4. **定时任务** - 支持 crontab 和 Hermes cronjob 定时生成报告
5. **微信推送** - 通过 Hermes cronjob 定时推送到微信

## 使用方法

### 直接生成图片

```bash
node scripts/fund_image_playwright.js
```

### 使用脚本生成（推荐）

```bash
chmod +x scripts/fund_generate_image.sh
./scripts/fund_generate_image.sh
```

生成的图片保存在 `~/.fund_reports/screenshots/` 目录下。

### 定时任务配置（推荐 Hermes cronjob）

#### 方法一：Hermes cronjob（支持微信推送）

使用 Hermes 的 cronjob 功能，可以定时直接在微信上收到基金报告：

```javascript
// 创建 11:50 的定时任务
cronjob action=create 
  name=fund-report-1150 
  schedule="50 11 * * 1-5"
  prompt="请运行基金报告生成脚本，然后把生成的图片发送给我。脚本路径：/path/to/scripts/fund_generate_image.sh。图片会保存在 ~/.fund_reports/screenshots/latest.png，请用 MEDIA 格式发送这个图片，并附带一个简短的基金报告总结。"

// 创建 14:50 的定时任务
cronjob action=create 
  name=fund-report-1450 
  schedule="50 14 * * 1-5"
  prompt="请运行基金报告生成脚本，然后把生成的图片发送给我。脚本路径：/path/to/scripts/fund_generate_image.sh。图片会保存在 ~/.fund_reports/screenshots/latest.png，请用 MEDIA 格式发送这个图片，并附带一个简短的基金报告总结。"

// 查看定时任务
cronjob action=list
```

#### 方法二：传统 crontab

添加到 crontab：

```bash
# 交易日 11:50 生成
50 11 * * 1-5 /path/to/scripts/fund_generate_image.sh

# 交易日 14:50 生成
50 14 * * 1-5 /path/to/scripts/fund_generate_image.sh
```

## 配置文件

修改脚本中的基金代码列表：

```javascript
// fund_image_playwright.js
const FUNDS = [
  "013273", "004070", "024618", "007883", "013172",
  "006195", "024003", "021458", "012414", "018561",
  "014415"
];
```

## 依赖

- Node.js
- Playwright

安装依赖：

```bash
npm install
npx playwright install chromium --with-deps
```

## 输出示例

- 图片尺寸：700 x (100 + 80*n) 像素
- 包含：标题、时间、基金列表、平均涨跌幅
- 涨跌颜色：红色涨、绿色跌

## 目录结构

```
.
├── README.md
├── SKILL.md
├── package.json
└── scripts
    ├── fund_image_playwright.js   # 核心图片生成脚本
    ├── fund_generate_image.sh     # 生成脚本（无 OpenClaw）
    └── fund_push_image_v2.sh      # 原推送脚本（需要 OpenClaw）
```

## 故障排除

1. **Playwright 未找到浏览器** - 确保已安装 Chromium：`npx playwright install chromium`
2. **基金数据获取失败** - 检查网络连接，API 可能有频率限制
3. **Hermes cronjob 未执行** - 检查任务状态：`cronjob action=list`