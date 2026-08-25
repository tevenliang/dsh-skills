"""
输出格式化：把 cells 渲染成 Markdown 表格 / 纯文本。

设计：输出和读取分离，便于以后接不同输出格式（plain / json / markdown）。
"""

from field_defs import get_field_name


def format_row_markdown(cells: list[dict], show_empty: bool = False) -> str:
    """
    把一行的 cells 渲染成 Markdown 表格。

    cells: [{col, row, value, raw?}]（col 0-based）
    show_empty: 是否展示空字段（默认 False,空字段不展示）
    """
    lines = ["| # | 字段 | 值 |", "|---|------|----|"]

    shown = 0
    for cell in cells:
        col = cell["col"]
        val = (cell.get("value", "") or "").strip()
        fname = get_field_name(col + 1)  # field_defs 是 1-based

        if not val and not show_empty:
            continue

        shown += 1
        # 替换换行符便于表格展示
        val_display = val.replace("\n", " ⏎ ")
        if len(val_display) > 120:
            val_display = val_display[:120] + "..."

        lines.append(f"| {col + 1} | **{fname}** | {val_display} |")

    if shown == 0:
        return "_(空行)_"

    # 末尾加统计行
    total = len(cells)
    lines.append(f"\n> 共展示 {shown} 个非空字段(共 {total} 个 cell)")

    return "\n".join(lines)


def format_row_full(cells: list[dict]) -> str:
    """
    把一行的 cells 渲染成完整原文（每个字段单独一段）。
    用于 review 模式或 --verbose 输出。
    """
    lines = []
    for cell in cells:
        col = cell["col"]
        val = (cell.get("value", "") or "").strip()
        fname = get_field_name(col + 1)
        if not val:
            continue
        lines.append(f"\n【{col + 1}. {fname}】")
        lines.append(val)

    return "\n".join(lines) if lines else "_(空行)_"


def format_search_results(rows: list[dict]) -> str:
    """
    渲染"客户名匹配"列表（行号 + 客户名 + 列号）。
    rows: [{"row": 2, "value": "...", "col": 0}]
    """
    if not rows:
        return "❌ 未找到匹配客户"

    lines = [f"✅ 找到 {len(rows)} 个匹配:"]
    for r in rows:
        lines.append(f"  - 行 {r['row'] + 1}（0-based {r['row']}）:{r['value']}")
    return "\n".join(lines)


def format_customer_summary(row_num: int, cells: list[dict]) -> str:
    """
    渲染单个客户的完整结果（顶部匹配信息 + Markdown 表格）。
    """
    name_cell = next((c for c in cells if c["col"] == 0), None)
    customer_name = name_cell["value"] if name_cell else f"行 {row_num + 1}"

    lines = [
        f"## ✅ 找到客户(行 {row_num + 1}):{customer_name}\n",
        format_row_markdown(cells),
    ]
    return "\n".join(lines)
