from __future__ import annotations
#!/usr/bin/env python3
"""
customer-update CLI: 客户资料新建/更新(Excel 版)

LLM 解析 → 22 字段 JSON → upsert 守卫 → 直接写云端 Excel

用法:
  python3 update.py '<LLM 解析后的 22 字段 JSON>'

JSON 格式(22 个字段,字段名 = field_defs.EXCEL_FIELDS 第 2 列):
{
  "客户名称": "无锡村田电子有限公司",        # 必填
  "行业": "电子",
  "销售阶段": "建联",                       # 通常留空让用户手动
  "客户标签": "KA",
  "联系人": "山田克己 董事长",               # 多行,追加用换行
  "公司简介": "...",
  "产品服务": "...",
  "财务状况": "...",
  "下游": "...",
  "营收": "未公开",
  "人数": "10000+",
  "网站": "https://www.murata.com",
  "地址": "无锡出口加工区...",
  "竞争对手": "TDK, TAIYO YUDEN",
  "城市": "无锡",
  "备注": "...",                             # = 7. 企业信息收集
  "更新日期": "2026-08-07"                   # 自动写今天
}

模式:
  - 新增:客户名搜不到 → 自动 append 新行
  - 更新:客户名搜到 → upsert 守卫后覆盖指定列
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# 统一合并后所有模块同目录,直接把脚本目录加入 sys.path 即可互相 import
sys.path.insert(0, str(Path(__file__).parent))

from kdocs_client import (
    find_customer_rows,
    get_row,
    update_cells,
    add_row,
    KdocsError,
)
from field_defs import (
    FIELD_TO_COL,
    EXCEL_FIELDS,
    SINGLE_VALUE_FIELDS,
    MULTILINE_FIELDS,
    TOTAL_COLS,
)

# customer-update 管辖的列(外部信息字段)
# 销售内部字段留 customer-record
UPDATE_FIELDS = {
    "行业", "客户标签", "联系人",
    "公司简介", "产品服务", "财务状况",
    "下游", "营收", "人数", "网站", "地址",
    "竞争对手", "城市", "备注",
    # "客户记录" / "下一步计划" / "下一步行动" / "销售阶段" — 留给 customer-record/手动
}


def sanitize_list_bullet(value: str) -> str:
    """sanitize 多行文本中的列表前缀,绕开 kdocs-cli Internal error bug。

    kdocs-cli 在写入 '- '(英文短横线 + 空格)开头的多行内容时会返回
    'Internal error',联系人/产品服务/备注等列表字段会写失败。

    策略: 把每行行首的 '- ' 替换成 '• '(Unicode bullet 字符)。
    视觉等价(列表效果一致),但能稳定写入。

    保留不动的情况(避免误改):
    - 行内中间的 '-' / '--'(如电话分隔符、价格区间)
    - 中文破折号 '—' / 全角短横线 '－'(不触发 bug)
    - 已经用其他 bullet(* • → ▸ 1. 等)开头
    - 行尾的 '-' 或单独的 '-'
    """
    if not value:
        return value
    out_lines = []
    for line in value.split("\n"):
        stripped = line.lstrip()
        indent = line[:len(line) - len(stripped)]
        if stripped.startswith("- "):
            # "- xxx" → "• xxx"
            out_lines.append(f"{indent}• {stripped[2:]}")
        elif stripped == "-":
            # 单独的 "-" → "•"
            out_lines.append(f"{indent}•")
        else:
            out_lines.append(line)
    return "\n".join(out_lines)

# ─────────────────────────────────────────────────────────────────────────────
# sanitize_markdown: 清理字段值里嵌入的 markdown 标记(v2.3+)
#
# 问题背景:LLM 解析阶段会把调研报告里的 markdown 表格/标题/加粗原样塞进
# 字段值,导致 vault frontmatter 的多行字段值里嵌套了 markdown,渲染时
# 「逃逸」到正文区域看着错乱。
#
# 清理规则:
#   - markdown 表格 → bullet 列表("• col1: col2")
#   - ##/### 标题 → 【标题】
#   - **加粗** → 去标记,保留文本
#   - --- 横线 → 删除
#   - 连续空行 → 合并
#
# 例外("备注"字段跳过此清理):
#   - 备注字段 = 调研报告归集处,可以保留 markdown
#   - 在 upsert_merge/build_new_row 调用时单独处理
# ─────────────────────────────────────────────────────────────────────────────

def sanitize_markdown(value: str) -> str:
    """清理字段值里嵌入的 markdown 标记(表格/标题/加粗/横线/链接/空行)。"""
    if not value:
        return value
    # v2.4: 先截断 LLM 解析残留的搜索结果 dump,然后去剩余 markdown 链接
    value = strip_search_result_dump(value)
    value = strip_markdown_link(value)

    def strip_bold(s):
        return re.sub(r"\*\*(.+?)\*\*", r"\1", s)

    lines = value.split("\n")
    out_lines = []
    table_buffer = []

    def flush_table():
        if not table_buffer:
            return
        if len(table_buffer) >= 2 and re.match(r"^[\|][\s\-:|]+[\|]$", table_buffer[1].strip()):
            header_cells = [strip_bold(c.strip()) for c in table_buffer[0].strip().strip("|").split("|")]
            for row_line in table_buffer[2:]:
                cells = [strip_bold(c.strip()) for c in row_line.strip().strip("|").split("|")]
                if len(cells) == len(header_cells):
                    parts = [f"{h}: {c}" for h, c in zip(header_cells, cells) if c]
                    if parts:
                        out_lines.append(f"• {'; '.join(parts)}")
                elif cells:
                    cells_clean = [c for c in cells if c]
                    if cells_clean:
                        out_lines.append(f"• {'; '.join(cells_clean)}")
        else:
            out_lines.extend(table_buffer)
        table_buffer.clear()

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            table_buffer.append(line)
            continue
        flush_table()

        m = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if m:
            out_lines.append(f"【{strip_bold(m.group(2))}】")
            continue

        if stripped == "---":
            continue

        out_lines.append(strip_bold(line))

    flush_table()

    result = []
    prev_empty = False
    for line in out_lines:
        is_empty = not line.strip()
        if is_empty and prev_empty:
            continue
        result.append(line)
        prev_empty = is_empty

    return "\n".join(result).strip()



def strip_search_result_dump(value: str) -> str:
    """去掉 LLM 解析时残留的搜索结果 dump(从第一个 'X. [text](url)' 模式开始截断)。

    背景:customer-update 的 LLM 解析阶段会把水滴/元宝搜索结果带 [title](url) 链接
    + "- 摘要:" "- 内容发布时间:" 等元数据塞进产品服务/公司简介等字段。
    实际字段值结构: [干净总结] + [搜索结果 dump]。
    策略:从搜索结果区开始截断,只留前面的干净总结。

    检测模式:
      - "1. [text](url)" 编号链接
      - "- 摘要:" / "- 内容发布时间:" / "- 网站:" / "- 相关图片:" / "- 来源:" 元数据
    """
    if not value:
        return value
    lines = value.split("\n")
    cut_idx = len(lines)
    for i, line in enumerate(lines):
        # 模式 1: 编号链接 "1. [text](url)" / "2. [..."
        if re.match(r"^\s*\d+\.\s*\[.+?\]\(.+?\)", line):
            cut_idx = i
            break
        # 模式 2: 搜索结果元数据 "- 摘要:" / "- 内容发布时间:" 等
        if re.match(r"^\s*-\s*(摘要|内容发布时间|网站|相关图片|来源)\s*[:：]", line):
            cut_idx = i
            break
    return "\n".join(lines[:cut_idx]).rstrip()


def strip_markdown_link(value: str) -> str:
    """去 markdown 链接语法,保留链接文字:`[text](url)` → `text`"""
    if not value:
        return value
    # 先处理图片(避免被 link 误吃)
    value = re.sub(r"!\[([^\]]*?)\]\([^\)]+?\)", "", value)
    # 再处理普通链接
    value = re.sub(r"\[([^\]]+?)\]\([^\)]+?\)", r"\1", value)
    return value


# 不进 sanitize_markdown 的字段(备注 = 调研报告归集处,可保留 markdown)
SANITIZE_MARKDOWN_SKIP = {"备注"}


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def find_or_confirm_new(customer_name: str) -> tuple[int | None, bool]:
    """
    找客户。返回 (row_0based, is_new)。
    - 命中 1 行 → (row, False) → 更新模式
    - 命中 0 行 → (None, True) → 新增模式
    - 命中多行 → 报错
    """
    matches = find_customer_rows(customer_name, col=0)
    if len(matches) > 1:
        names = "\n  ".join(f"行 {m['row'] + 1}: {m['value']}" for m in matches)
        raise KdocsError(
            f"命中 {len(matches)} 个同名客户,请用更精确的关键词:\n  {names}"
        )
    if matches:
        return matches[0]["row"], False
    return None, True


def upsert_merge(row: int, payload: dict) -> list[dict]:
    """
    upsert 守卫:payload 字段空 → 保留 Excel 现有值。
    返回 update_cells 的 cells 数组。
    """
    cells = get_row(row, 0, 21)
    current = {c["col"]: c["value"] for c in cells}

    updates = []
    for field, new_val in payload.items():
        if field == "客户名称":
            continue  # 客户名称不更新
        if field not in UPDATE_FIELDS:
            print(f"⚠️ 「{field}」不在 customer-update 管辖范围,跳过(留 customer-record/手动)")
            continue

        col_1based = FIELD_TO_COL.get(field)
        if not col_1based:
            continue
        col_0based = col_1based - 1
        cur_val = (current.get(col_0based) or "").strip()
        new_val = (str(new_val) if new_val is not None else "").strip()

        if not new_val:
            # 源端空 → 保留对端(upsert 守卫)
            print(f"  ⏭ {field}: 源端空,保留现有")
            continue

        # 多行字段做 sanitize(避 kdocs-cli Internal error bug + 防 markdown 逃逸)
        if field in MULTILINE_FIELDS:
            # v2.3: 先清掉字段值里嵌入的 markdown 表格/标题/加粗("备注"字段例外)
            if field not in SANITIZE_MARKDOWN_SKIP:
                new_val = sanitize_markdown(new_val)
            # 再把 "- " 列表前缀换成 "• "(绕 kdocs-cli Internal error)
            new_val = sanitize_list_bullet(new_val)

        if new_val == cur_val:
            print(f"  ⏭ {field}: 与现有相同,跳过")
            continue

        updates.append({"row": row, "col": col_0based, "value": new_val})

    # 自动写 更新日期
    col_0based = FIELD_TO_COL["更新日期"] - 1
    updates.append({"row": row, "col": col_0based, "value": today_str()})

    return updates


def build_new_row(payload: dict) -> list[str]:
    """
    新增模式:构造 22 列字符串数组(空字符串 = 该列不写)。
    """
    row = [""] * TOTAL_COLS
    for field, val in payload.items():
        if field == "客户名称":
            col_1based = 1
            val = val or ""
        else:
            col_1based = FIELD_TO_COL.get(field)
            if not col_1based:
                continue
        val = (str(val) if val is not None else "").strip()
        # 多行字段做 sanitize(避 kdocs-cli bug + 防 markdown 逃逸)
        if field in MULTILINE_FIELDS:
            # v2.3: 先清掉字段值里嵌入的 markdown("备注"字段例外)
            if field not in SANITIZE_MARKDOWN_SKIP:
                val = sanitize_markdown(val)
            # 再把 "- " 列表前缀换成 "• "
            val = sanitize_list_bullet(val)
        row[col_1based - 1] = val

    # 自动写 更新日期
    row[FIELD_TO_COL["更新日期"] - 1] = today_str()

    # 客户名称必填
    if not row[0]:
        raise KdocsError("新增客户时客户名称必填")

    return row


def main():
    parser = argparse.ArgumentParser(
        description="customer-update: 新建/更新客户外部信息字段到云端 Excel",
    )
    parser.add_argument("payload", nargs="?", help="JSON 字符串")
    parser.add_argument("--stdin", action="store_true", help="从 stdin 读 JSON")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只预览不写(虽然默认是直接写,但保留这个 flag 方便核对)",
    )
    args = parser.parse_args()

    if args.stdin:
        payload = json.loads(sys.stdin.read())
    elif args.payload:
        payload = json.loads(args.payload)
    else:
        print("❌ 必须提供 payload", file=sys.stderr)
        sys.exit(1)

    customer_name = (payload.get("客户名称") or "").strip()
    if not customer_name:
        print("❌ payload 缺少「客户名称」", file=sys.stderr)
        sys.exit(1)

    print(f"📋 客户: {customer_name}")
    print(f"📝 待写入字段: {[k for k in payload if k != '客户名称']}\n")

    # 1. 找客户
    try:
        row, is_new = find_or_confirm_new(customer_name)
    except KdocsError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(2)

    if is_new:
        print("🆕 客户不存在 → 新增模式")
        try:
            values = build_new_row(payload)
        except KdocsError as e:
            print(f"❌ {e}", file=sys.stderr)
            sys.exit(3)

        if args.dry_run:
            print("\n📋 预览(新增 1 行):")
            for i, v in enumerate(values):
                if v:
                    print(f"  col {i + 1}: {v[:80]}")
            return

        print("\n💾 append 新行...")
        try:
            result = add_row(values)
            print(f"✅ 新增成功")
            # 读回新行号
            new_matches = find_customer_rows(customer_name, col=0)
            if new_matches:
                new_row = new_matches[0]["row"]
                print(f"   新行号: {new_row + 1}")
        except KdocsError as e:
            print(f"❌ 新增失败: {e}", file=sys.stderr)
            sys.exit(4)
    else:
        print(f"✅ 命中行 {row + 1} → 更新模式")
        updates = upsert_merge(row, payload)

        if not updates:
            print("\n💡 没有需要更新的字段(都被 upsert 守卫拦下了)")
            return

        if args.dry_run:
            print("\n📋 预览:")
            for u in updates:
                col_1based = u["col"] + 1
                fname = next((f for f, c in FIELD_TO_COL.items() if c == col_1based), "?")
                print(f"  col {col_1based} ({fname}): {u['value'][:80]}")
            return

        print(f"\n💾 写入云端 Excel({len(updates)} 个 cell)...")
        try:
            result = update_cells(updates)
            print(f"✅ 更新成功")
        except KdocsError as e:
            print(f"❌ 更新失败: {e}", file=sys.stderr)
            sys.exit(4)

    print(f"\n💡 需要 vault 同步吗?(手动触发 customer-vault,默认不用)")


if __name__ == "__main__":
    main()
