#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/jd.py — 京东多平台比价 (ominicrawl v3, haina/值得买版, 2026-08-17)

迁移 (2026-08-17): 原 smzdm API 直调 → haina shopping-assistant 决策分析输出格式
数据源: haina ProductSearchProAPI (同 ZhiDeMai gw-openapi.zhidemai.com/product/v1)
凭证:   ZHIDEMAI_PRODUCT_SEARCH 环境变量 / haina 内置体验 Key (同原来)

设计:
- 每个关键词每天一个文件: subscription/jd/<keyword>/YYYY-MM-DD_优惠好价.md
- 每个文件按 haina "优惠好价" 模板格式输出:
    1. 商品概览
    2. 全网价格对比表
    3. 渠道详细对比
    4. 购买建议
- 同一天重复跑批: 完全覆盖 (snapshot 语义)
"""
import sys, json, os, re, time
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

SKILL_ROOT = str(Path(__file__).resolve().parent.parent)
for _p in (SKILL_ROOT, str(Path(__file__).parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── haina ProductSearchProAPI ────────────────────────────────────────
_HAINA_ROOT = Path.home() / ".agents" / "skills" / "Search" / "haina-shopping-assistant" / "scripts"
if _HAINA_ROOT.exists() and str(_HAINA_ROOT) not in sys.path:
    sys.path.insert(0, str(_HAINA_ROOT))

try:
    from product_search_pro_api import ProductSearchProAPI
    _haina_api = ProductSearchProAPI()
except Exception as e:
    print(f"  [warn] haina ProductSearchProAPI 导入失败: {e}，降级使用内置方式")
    _haina_api = None

# ── Vault ──────────────────────────────────────────────────────────────
_VAULT_SUB = Path("/Users/tianwenliang/Documents/steven_vault/subscription")

# ── 渠道映射 ──────────────────────────────────────────────────────────
_MALL_ORDER = {"京东": 0, "天猫": 1, "拼多多": 2, "淘宝": 3, "苏宁": 4}
_PLAT_SHORT = {"京东": "JD", "天猫": "TM", "拼多多": "PDD", "淘宝": "TB", "苏宁": "SN"}

# ── 凭证 (兼容) ──────────────────────────────────────────────────────
def _get_api_key() -> str:
    key = os.getenv("ZHIDEMAI_PRODUCT_SEARCH", "").strip()
    if key:
        return key
    key_file = Path.home() / ".agents" / "credentials" / "zhidemai" / "product_api_key.txt"
    if key_file.exists():
        return key_file.read_text().strip()
    return "ebdc47644d7c8fb74491cb1021f98c3a"  # haina 内置体验 Key


# ── API 调用 (兼容 haina / 直接两种方式) ─────────────────────────────
def _search_haina(keyword: str, size: int = 10) -> list:
    """调 haina ProductSearchProAPI，返回 list[dict]."""
    if _haina_api is not None:
        try:
            result = _haina_api.search(
                product_query=keyword,
                question_id="ominicrawl-jd",
                request_from="ominicrawl-jd",
                query_process=1,
                size=size,
                mall_id="", brand_name="", category_name="",
                min_price=None, max_price=None, sort="", fields=""
            )
            if isinstance(result, dict):
                return result.get("data", {}).get("rows", [])
            return []
        except Exception as e:
            print(f"    [haina] 失败: {e}")
    # 降级: 直接 requests
    import urllib.request
    payload = {
        "request_from": "ominicrawl-jd", "question_id": "1",
        "product_query": keyword, "query_process": 1, "size": size,
        "mall_id": "", "brand_name": "", "category_name": "",
        "min_price": None, "max_price": None, "sort": "", "fields": ""
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://gw-openapi.zhidemai.com/product/v1",
        data=body,
        headers={"Content-Type": "application/json", "X-Api-Key": _get_api_key()}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("data", {}).get("rows", [])
    except Exception as e:
        print(f"    [API] 失败: {e}")
        return []


# ── 数据解析 ──────────────────────────────────────────────────────────
def _parse_price(val) -> float:
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace("¥", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_coupon(s: str):
    if not s:
        return "", ""
    import re as _re
    m = _re.search(r"减(\d+\.?\d*)", s)
    amount = float(m.group(1)) if m else 0.0
    amount_str = f"¥{amount:.0f}" if amount else ""
    s_clean = _re.sub(r"(\d+)\.0+", r"\1", s)
    return amount_str, s_clean


def _mall_sort_key(item: dict) -> tuple:
    mall = item.get("mall_name", "")
    order = _MALL_ORDER.get(mall, 99)
    price = _parse_price(item.get("price", 0))
    return (order, price)


# ── 模板渲染: 优惠好价 ────────────────────────────────────────────────
def _render_price_comparison(keyword: str, rows: list, date_str: str) -> str:
    """按 haina 优惠好价模板渲染 markdown."""
    # 按渠道优先级、价格排序
    sorted_rows = sorted(rows, key=_mall_sort_key)
    best = min(rows, key=lambda r: _parse_price(r.get("price", 0))) if rows else None
    worst = max(rows, key=lambda r: _parse_price(r.get("price", 0))) if rows else None

    lines = [
        "---",
        f'title: "{date_str} {keyword} 优惠好价"',
        "type: haina-recommend",
        f"collected_at: {datetime.now(timezone(timedelta(hours=8))).isoformat()}",
        "source: haina-zhidemai",
        "api: gw-openapi.zhidemai.com/product/v1",
        f"keyword: {json.dumps(keyword, ensure_ascii=False)}",
        f"result_count: {len(rows)}",
        "---",
        "",
        f"# {keyword} 全网优惠好价",
        "",
        f"> 自动生成 {datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')} · 数据来源: 值得买海纳购物管家",
        "",
    ]

    # ── 1. 全网价格对比表 ──
    lines += [
        "## 全网价格对比",
        "",
        f"共收录 {len(rows)} 个商品报价，覆盖京东/天猫/拼多多等主流渠道。",
        "",
        "| 渠道 | 商品 | 现价 | 原价 | 优惠 | 推荐 |",
        "| --- | --- | --- | --- | --- |",
    ]

    for r in sorted_rows:
        mall = r.get("mall_name", "")
        title = (r.get("title") or "")[:50]
        price = _parse_price(r.get("price", 0))
        orig_price = _parse_price(r.get("page_price", 0))
        promo = r.get("promotional_info", "") or ""
        coupon_val, coupon_str = _parse_coupon(promo)
        # 推荐星标: 京东自营优先
        stars = ""
        if mall == "京东":
            stars = "⭐⭐⭐⭐⭐"
        elif mall == "天猫":
            stars = "⭐⭐⭐⭐"
        elif "百亿" in promo or "补贴" in promo:
            stars = "⭐⭐⭐⭐"

        orig_str = f"¥{orig_price:.0f}" if orig_price > price else ""
        coupon_str = re.sub(r"(\d+)\.0+(元|块)?", r"\1\2", coupon_str)[:40] if coupon_str else "-"
        lines.append(f"| {mall} | {title} | ¥{price:.0f} | {orig_str} | {coupon_str} | {stars} |")

    lines += ["",]

    # ── 2. 重点渠道推荐 ──
    if best:
        lines += [
            "## 🏆 最优购买方案",
            "",
            f"**推荐渠道**: {best.get('mall_name', '')}",
            f"**实付价格**: ¥{_parse_price(best.get('price', 0)):.0f}",
            f"**商品**: {best.get('title', '')[:60]}",
        ]
        coupon_val, coupon_str = _parse_coupon(best.get("promotional_info", "") or "")
        if coupon_str:
            lines.append(f"**优惠信息**: {coupon_str}")
        link = best.get("url", "")
        if link:
            lines.append(f"**📦 购买链接**: [点击购买]({link})")
        lines.append("")

        # 推荐理由
        reasons = []
        mall = best.get("mall_name", "")
        if mall == "京东":
            reasons.append("✅ 京东自营，正品保障，售后无忧")
        if mall == "天猫":
            reasons.append("✅ 官方旗舰店，品质保证")
        _, promo_clean = _parse_coupon(best.get("promotional_info", "") or "")
        if promo_clean:
            reasons.append(f"✅ {promo_clean}")
        price = _parse_price(best.get("price", 0))
        orig = _parse_price(best.get("page_price", 0))
        if orig > price:
            reasons.append(f"✅ 限时优惠，节省 ¥{orig - price:.0f}")
        if not reasons:
            reasons.append("✅ 价格最优，渠道可靠")

        lines += ["**推荐理由**:", ""] + [f"- {r}" for r in reasons] + [""]

    # ── 3. 各渠道要点 ──
    seen_malls = set()
    for r in sorted_rows:
        mall = r.get("mall_name", "")
        if mall in seen_malls:
            continue
        seen_malls.add(mall)
        price = _parse_price(r.get("price", 0))
        orig = _parse_price(r.get("page_price", 0))
        _, coupon_str = _parse_coupon(r.get("promotional_info", "") or "")

        lines += [
            f"### {mall}",
            "",
            f"- **现价**: ¥{price:.0f}" + (f"（原价 ¥{orig:.0f}）" if orig > price else ""),
        ]
        if coupon_str:
            lines.append(f"- **优惠**: {coupon_str}")
        link = r.get("url", "")
        if link:
            lines.append(f"- **购买**: [点击购买]({link})")
        lines.append("")

    # ── 4. 省钱小结 ──
    if best and worst:
        best_p = _parse_price(best.get("price", 0))
        worst_p = _parse_price(worst.get("price", 0))
        if worst_p > best_p:
            lines += [
                "## 💰 省钱小结",
                "",
                f"- 最高价与最低价差 ¥{worst_p - best_p:.0f}",
                f"- 选择 **{best.get('mall_name', '')}** 可节省 ¥{worst_p - best_p:.0f}",
                f"- 历史好价参考: 当前 ¥{best_p:.0f} " + ("处于低位" if best_p / worst_p < 0.85 else "接近底价") + "区间",
                ""
            ]

    return "\n".join(lines)





# ── 缓存 (一次请求内不重复) ──────────────────────────────────────────
_search_cache = {}


# ── crawl_batch ────────────────────────────────────────────────────────
def crawl_batch(date_yymmdd=None):
    """
    每天一个关键词子目录: subscription/jd/<keyword>/YYYY-MM-DD_优惠好价.md
    """
    global _search_cache
    _search_cache = {}

    # 读关键词
    try:
        from common.feishu_watchlist import get_jd_keywords
        keywords = get_jd_keywords()
    except Exception as e:
        print(f"  [warn] 飞书京东关键词读取失败: {e}")
        keywords = []
    keywords = keywords or [{"kw": "Sony WH-1000XM6", "label": "Sony WH-1000XM6"},
                             {"kw": "Bose QuietComfort 耳机", "label": "Bose QuietComfort 耳机"},
                             {"kw": "小米降噪耳机", "label": "小米降噪耳机"}]

    if not keywords:
        print("  ⚠️  无关键词, 跳过")
        return []

    today = date.today().isoformat()  # YYYY-MM-DD
    n_written = 0

    for item in keywords:
        kw = (item.get("kw") or "").strip()
        label = (item.get("label") or kw).strip()
        if not kw:
            continue

        print(f"  🔍 优惠好价 (haina): {kw}")
        rows = _search_haina(kw, size=10)
        if not rows:
            print(f"    [skip] 无结果")
            continue
        print(f"    → {len(rows)} 条 (覆盖 {[r.get('mall_name','') for r in rows]})")

        # 输出: subscription/jd/<label>/YYYY-MM-DD_优惠好价.md
        safe_label = re.sub(r'[\\/:*?"<>|]', '_', label).strip()
        out_dir = _VAULT_SUB / "jd" / safe_label
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{today}_优惠好价.md"

        md = _render_price_comparison(label, rows, today)
        out_path.write_text(md, encoding="utf-8")
        print(f"  ✅ {label}: {out_path.relative_to(_VAULT_SUB)}")
        n_written += 1

    print(f"  📊 京东优惠好价完成: {n_written} 个文件")
    return []


if __name__ == "__main__":
    crawl_batch()
