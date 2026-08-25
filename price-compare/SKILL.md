---
name: price-compare
description: 三平台比价省钱助手：查价格、找优惠券、解析口令、转链接。当用户需要比较京东/淘宝/拼多多价格、找最便宜平台、查优惠链接时使用。触发词：比价、哪里买最便宜、价格监控、帮我查XX在哪买、优惠券。
agent_created: false
disable-model-invocation: true
---

# PriceCompare · 购物省钱宝

三平台比价省钱助手：查价格、找优惠券、解析口令、转链接。帮我查XX在哪买最便宜。

**数据源**：`http://op.squirrel2.cn/api/v1/{endpoint}`（纯 HTTP，不需要浏览器）

## 功能

### 1. 链接转链 `convert_link`
将商品链接转换为优惠链接。

```
触发条件: 用户发送了电商商品链接
API:      POST /api/v1/convert  body: {"url": "...", "platform": "jd|taobao|pinduoduo"}
```

平台自动识别域名:
- JD: item.jd.com, u.jd.com, 3.cn
- TB: item.taobao.com, detail.tmall.com, m.tb.cn, e.tb.cn
- PDD: mobile.yangkeduo.com, p.pinduoduo.com

### 2. 口令解析 `parse_share_content`
解析用户粘贴的电商分享内容（口令、短链接等）。

```
触发条件: 用户发送了疑似分享口令的文本（非纯 URL）
API:      POST /api/v1/parse_share  body: {"content": "<用户原话>"}
```

### 3. 商品搜索 `search_goods`
按关键词搜索商品。不指定 platform 时自动走三平台比价。

```
触发条件: 用户想搜索/找某类商品
API:      POST /api/v1/search  body: {"platform": "jd|taobao|pinduoduo", "keyword": "...", "page_size": 10}

platform 为 None: 自动调用 compare_prices 三平台比价
page_size 最小值: 10
```

### 4. 多平台比价 `compare_prices`
同一关键词在京东/淘宝/拼多多三平台同时搜索，返回最低价。

```
触发条件: 用户想对比价格、找最便宜的平台
API:      POST /api/v1/compare  body: {"keyword": "..."}
```

## 路由决策

| 优先级 | 条件 | 调用 |
|--------|------|------|
| 1 | message 含电商商品 URL | `convert_link(url)` |
| 2 | 其他文本 | `parse_share_content(message)` → 失败则 `search_goods(keyword)` |

## 响应字段

| 字段 | 类型 | 含义 |
|------|------|------|
| title | string | 商品名称 |
| price | number | 券后价（元） |
| originalPrice | number | 原价（元） |
| couponInfo | string | 优惠券描述 |
| couponAmount | number | 优惠券面值（元） |
| shopName | string | 店铺名称 |
| monthSales | string | 月销量 |
| link | string | 优惠购买链接 |
| platform | string | 平台代码（jd/taobao/pinduoduo） |

## 错误处理

- 口令过期/无效 → 告知用户重新获取
- 商品下架 → 告知不可购买，建议搜索同类
- 无搜索结果 → 建议放宽关键词
- parse_share 失败 → 自动 fallback 到商品搜索
- API 异常 → 提示服务暂时不可用
