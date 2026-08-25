#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jd_dedupe_offline.py — 离线精简旧格式多平台比价 md 文件 (2026-08-04)

用途:
  旧的 2026-08-04_多平台比价.md 是 8 列格式 (商品/平台/现价/原价/月销/店铺/优惠券/购买链接),
  没有按 (平台, 现价) 去重. 本工具按 (平台, 现价) 去重, 同组保留月销最高,
  并输出新格式 6 列 (去掉 原价 / 店铺).

用法:
  python3 tools/jd_dedupe_offline.py <md_path> [--in-place] [--dry-run]

示例:
  python3 tools/jd_dedupe_offline.py \\
    /Users/tianwenliang/Documents/steven_vault/subscription/jd/多平台比价/2026-08-04_多平台比价.md \\
    --in-place
"""
import argparse
import re
import sys
from pathlib import Path

# 让脚本能找到 ingest-search/jd.py 里的辅助函数
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 直接复制 _parse_sales 实现, 不依赖 ingest_search 包路径
def _parse_sales(s) -> float:
    """月销量解析: 支持 '4' / '1.5万+' / '1000+' / '' 等格式."""
    s = str(s or "").strip()
    if not s:
        return 0.0
    if "万" in s:
        n = s.replace("万", "").replace("+", "").strip()
        try:
            return float(n) * 10000
        except ValueError:
            return 0.0
    s_clean = s.replace("+", "").strip()
    try:
        return float(s_clean)
    except ValueError:
        return 0.0


_PLAT_LABEL = {"京东": "jd", "拼多多": "pdd", "淘宝": "taobao"}
_PLAT_LABEL_REV = {"jd": "京东", "pdd": "拼多多", "taobao": "淘宝"}
_PLAT_ORDER = {"jd": 0, "pdd": 1, "taobao": 2}

# 匹配 markdown 链接 [text](url) 或裸文本
_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
_PRICE_RE = re.compile(r"¥?\s*(\d+(?:\.\d+)?)")


def _split_md_row(line: str) -> list[str]:
    """去除首尾 |, 按 | 切分, 保留空 cell."""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _first_link(cell: str):
    """从 cell 中提取第一个 markdown 链接的 (text, url). 没有则 (cell, '')."""
    m = _LINK_RE.search(cell)
    if m:
        return m.group(1), m.group(2)
    return cell, ""


def _parse_price(price_cell: str) -> float:
    m = _PRICE_RE.search(price_cell)
    if not m:
        return 0.0
    try:
        return round(float(m.group(1)), 2)
    except ValueError:
        return 0.0


def _parse_old_row(row_cells: list[str]) -> dict | None:
    """从 8 列旧格式 row 解析出 item 字典. 失败返回 None."""
    if len(row_cells) < 6:
        return None
    title_cell = row_cells[0]
    plat_cell = row_cells[1]
    price_cell = row_cells[2]
    # row_cells[3] = 原价 (丢弃)
    sales_cell = row_cells[4]
    # row_cells[5] = 店铺 (丢弃)
    coupon_cell = row_cells[6] if len(row_cells) > 6 else "-"
    link_cell = row_cells[7] if len(row_cells) > 7 else ""

    title, link = _first_link(title_cell)
    if not link_cell:
        # 旧格式可能 link 在最后一格 [购买](url)
        _, link = _first_link(link_cell)
    plat = _PLAT_LABEL.get(plat_cell.strip(), plat_cell.strip())

    return {
        "title": title.strip(),
        "shortTitle": title.strip()[:60],
        "link": link.strip(),
        "price": _parse_price(price_cell),
        "monthSales": sales_cell.strip() or "0",
        "couponInfo": "" if coupon_cell.strip() in ("-", "") else coupon_cell.strip(),
        "platform": plat,
    }


def _dedupe_section(rows: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    """按 (平台, 现价) 去重, 同组保留月销最高. 返回按 (平台序, -月销) 排序的列表."""
    best = {}  # (plat, price) -> (item, sales)
    for plat, item in rows:
        key = (plat, item["price"])
        sales = _parse_sales(item.get("monthSales", 0))
        if key not in best or sales > best[key][1]:
            best[key] = (item, sales)
    result = [(plat, item) for (plat, _), (item, _) in best.items()]
    result.sort(key=lambda x: (
        _PLAT_ORDER.get(x[0], 99),
        -_parse_sales(x[1].get("monthSales", 0)),
    ))
    return result


def _render_section(label: str, rows: list[tuple[str, dict]]) -> str:
    deduped = _dedupe_section(rows)
    if not deduped:
        return ""
    lines = [f"# {label}", ""]
    lines.append("| 商品 | 平台 | 现价 | 月销 | 优惠券 | 购买链接 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for plat, item in deduped:
        title = (item.get("shortTitle") or item.get("title", ""))[:60]
        link = item.get("link", "")
        title_md = f"[{title}]({link})" if link else title
        plat_label = _PLAT_LABEL_REV.get(plat, plat)
        coupon = item.get("couponInfo", "") or "-"
        lines.append(
            f"| {title_md} | {plat_label} | ¥{item['price']} | {item['monthSales']} | {coupon} | "
            f"[购买]({link}) |"
        )
    return "\n".join(lines) + "\n"


def dedupe_md(text: str) -> str:
    """对整份 md 做去重 + 精简."""
    lines = text.split("\n")
    # 1. 保留 frontmatter
    out_lines = []
    i = 0
    in_front = False
    front_done = False
    while i < len(lines):
        line = lines[i]
        if not front_done and line.strip() == "---":
            if not in_front:
                in_front = True
                out_lines.append(line)
                i += 1
                continue
            else:
                # closing ---
                out_lines.append(line)
                in_front = False
                front_done = True
                i += 1
                continue
        if in_front or not front_done:
            out_lines.append(line)
            i += 1
            continue
        # frontmatter 之后
        if line.startswith("# "):
            label = line[2:].strip()
            # 找 section 结束 (下一个 # 或 文件尾)
            j = i + 1
            section_rows = []
            while j < len(lines) and not lines[j].startswith("# "):
                l = lines[j]
                if l.startswith("|") and not l.startswith("| ---") and "--- |" not in l and "商品 |" not in l:
                    cells = _split_md_row(l)
                    item = _parse_old_row(cells)
                    if item:
                        section_rows.append((item["platform"], item))
                j += 1
            # 渲染该 section
            sec_md = _render_section(label, section_rows)
            if sec_md:
                out_lines.append("")
                out_lines.append(sec_md.rstrip())
                out_lines.append("")
            i = j
            continue
        else:
            out_lines.append(line)
            i += 1
    return "\n".join(out_lines).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("md_path", type=Path)
    ap.add_argument("--in-place", action="store_true", help="直接覆盖原文件")
    ap.add_argument("--dry-run", action="store_true", help="只打印新内容到 stdout, 不写文件")
    args = ap.parse_args()

    src = args.md_path.read_text(encoding="utf-8")
    new = dedupe_md(src)

    # 统计
    src_lines = src.count("\n")
    new_lines = new.count("\n")
    src_table_rows = sum(1 for ln in src.split("\n") if ln.startswith("|") and "商品 |" not in ln and "--- |" not in ln)
    new_table_rows = sum(1 for ln in new.split("\n") if ln.startswith("|") and "商品 |" not in ln and "--- |" not in ln)

    print(f"原文件:    {src_lines} 行, {src_table_rows} 表行, {len(src)} bytes")
    print(f"精简后:    {new_lines} 行, {new_table_rows} 表行, {len(new)} bytes")
    print(f"压缩比:    表行 {new_table_rows}/{src_table_rows} = {new_table_rows*100//src_table_rows}%")
    print(f"减幅:      表行 -{src_table_rows - new_table_rows} 行, 字节 -{len(src) - len(new)}")

    if args.dry_run:
        print("\n--- 新内容 (前 30 行) ---")
        for ln in new.split("\n")[:30]:
            print(ln)
    elif args.in_place:
        args.md_path.write_text(new, encoding="utf-8")
        print(f"✅ 已覆盖写回: {args.md_path}")
    else:
        out = args.md_path.with_suffix(".deduped.md")
        out.write_text(new, encoding="utf-8")
        print(f"✅ 已写到: {out}")


if __name__ == "__main__":
    main()
