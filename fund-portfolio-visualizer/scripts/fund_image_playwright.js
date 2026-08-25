#!/usr/bin/env node
/**
 * 基金池估值图生成器 - 使用 Playwright 截图
 * 生成 HTML → 使用 Playwright 截图 → 生成 PNG
 */

const https = require('https');
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const FUNDS = [
  "013273", "004070", "024618", "007883", "013172",
  "006195", "024003", "021458", "012414", "018561",
  "014415"
];

function fetchFundData(fundCode) {
  return new Promise((resolve) => {
    const url = `https://fundgz.1234567.com.cn/js/${fundCode}.js?rt=${Date.now()}`;
    https.get(url, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          const match = data.match(/jsonpgz\((.+?)\);/);
          if (match) {
            const json = JSON.parse(match[1]);
            resolve({
              code: json.fundcode || fundCode,
              name: json.name || `基金${fundCode}`,
              nav: json.dwjz || '--',
              estimateNav: json.gsz || '--',
              change: json.gszzl || '--',
              time: json.gztime || '--'
            });
          } else {
            resolve({ code: fundCode, name: `基金${fundCode}`, nav: '--', estimateNav: '--', change: '--', time: '--' });
          }
        } catch (e) {
          resolve({ code: fundCode, name: `基金${fundCode}`, nav: '--', estimateNav: '--', change: '--', time: '--' });
        }
      });
    }).on('error', () => {
      resolve({ code: fundCode, name: `基金${fundCode}`, nav: '--', estimateNav: '--', change: '--', time: '--' });
    });
  });
}

function getChangeColor(change) {
  const val = parseFloat(change);
  if (val > 0) return '#FF4444';
  if (val < 0) return '#00AA00';
  return '#888888';
}

function getChangeArrow(change) {
  const val = parseFloat(change);
  if (val > 0) return '▲';
  if (val < 0) return '▼';
  return '—';
}

function formatChange(change) {
  if (change === '--' || change === undefined || change === null) {
    return { text: '暂无估值', color: '#888888', arrow: '—' };
  }
  const val = parseFloat(change);
  if (isNaN(val)) {
    return { text: '暂无估值', color: '#888888', arrow: '—' };
  }
  const text = val > 0 ? `+${val.toFixed(2)}%` : `${val.toFixed(2)}%`;
  const color = getChangeColor(change);
  const arrow = getChangeArrow(change);
  return { text, color, arrow };
}

async function generateFundImage() {
  console.log('正在获取基金数据...');
  const fundDataList = await Promise.all(FUNDS.map(code => fetchFundData(code)));
  
  const width = 700;
  const headerHeight = 100;
  const rowHeight = 80;
  const height = headerHeight + fundDataList.length * rowHeight;
  
  // 生成 HTML
  const now = new Date();
  const weekdays = ['日', '一', '二', '三', '四', '五', '六'];
  const datetimeStr = now.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
    weekday: 'long',
    timeZone: 'Asia/Shanghai'
  }).replace(/星期([一二三四五六日])/, (_, d) => `星期${d}`);
  
  // 统计信息
  let totalChange = 0;
  let validCount = 0;
  let latestTime = '';
  
  const rowsHtml = fundDataList.map((fund, index) => {
    const changeInfo = formatChange(fund.change);
    const bgColor = index % 2 === 1 ? '#f8f9fa' : '#ffffff';
    
    // 统计
    if (fund.change && fund.change !== '--') {
      const val = parseFloat(fund.change);
      if (!isNaN(val)) {
        totalChange += val;
        validCount++;
      }
    }
    if (fund.time && fund.time !== '--') {
      latestTime = fund.time;
    }
    
    return `
    <div class="fund-row" style="background: ${bgColor};">
      <div class="fund-info">
        <div class="fund-name">${fund.name}</div>
        <div class="fund-code">(${fund.code})</div>
      </div>
      <div class="fund-change" style="color: ${changeInfo.color}"><span class="arrow">${changeInfo.arrow}</span> ${changeInfo.text}</div>
    </div>`;
  }).join('');
  
  const avgChange = validCount > 0 ? (totalChange / validCount).toFixed(2) : '0.00';
  const avgChangeInfo = formatChange(avgChange);
  
  const html = `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { 
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", "PingFang SC", "Microsoft YaHei", sans-serif;
  background: white;
  width: ${width}px;
  height: ${height}px;
}
.container {
  width: 100%;
  height: 100%;
}
.header {
  width: 100%;
  height: ${headerHeight}px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  color: white;
}
.title {
  font-size: 32px;
  font-weight: bold;
  margin-bottom: 8px;
}
.datetime {
  font-size: 16px;
  opacity: 0.9;
}
.fund-row {
  width: 100%;
  height: ${rowHeight}px;
  display: flex;
  align-items: center;
  padding: 0 30px;
  border-bottom: 1px solid #e0e0e0;
}
.fund-info {
  flex: 1;
}
.fund-name {
  font-size: 20px;
  color: #333;
  margin-bottom: 5px;
}
.fund-code {
  font-size: 14px;
  color: #666;
}
.fund-change {
  font-size: 24px;
  font-weight: bold;
}
.arrow {
  display: inline-block;
  margin-right: 6px;
}
.footer {
  width: 100%;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 30px;
  background: #f0f0f0;
  font-size: 14px;
  color: #666;
}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="title">📊 基金实时估值</div>
    <div class="datetime">${datetimeStr}</div>
  </div>
  ${rowsHtml}
</div>
</body>
</html>`;
  
  // 保存 HTML 文件
  const outputDir = '/tmp/fund_screenshots';
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }
  
  const timestamp = now.toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const htmlPath = path.join(outputDir, `fund_report_${timestamp}.html`);
  const pngPath = path.join(outputDir, `fund_report_${timestamp}.png`);
  
  fs.writeFileSync(htmlPath, html);
  console.log('HTML 已生成:', htmlPath);
  
  // 使用 Playwright 截图
  console.log('正在截图...');
  const browser = await chromium.launch({
    headless: true
  });
  
  const page = await browser.newPage();
  await page.setViewportSize({ width, height });
  await page.goto(`file://${htmlPath}`);
  await page.waitForLoadState('networkidle');
  
  // 截图
  await page.screenshot({
    path: pngPath,
    type: 'png',
    fullPage: false
  });
  
  await browser.close();
  
  console.log('图片已保存:', pngPath);
  console.log(`平均估值: ${avgChangeInfo.arrow} ${avgChangeInfo.text}`);
  if (latestTime) {
    console.log(`估值时间: ${latestTime}`);
  }
  
  return { htmlPath, pngPath, fundDataList };
}

// 运行
if (require.main === module) {
  generateFundImage().catch(err => {
    console.error('错误:', err);
    process.exit(1);
  });
}

module.exports = { generateFundImage };
