#!/usr/bin/env python3
"""
customer-record CLI: 销售内部字段快速记录

LLM 解析 → JSON payload → 直接写云端 Excel(销售内部字段)

用法:
  python3 record.py '<LLM 解析后的 JSON>'

JSON 格式:
{
  "customer_name": "深圳市路演中网络科技有限公司",
  "writes": {
    "客户记录":   "通了电话,聊了合同细节",      # 追加 mmdd 前缀
    "下一步行动": "联系陈滢发合同",            # 覆盖
    "下一步计划": "2026-08-10",                # 覆盖(YYYY-MM-DD)
    "联系人":     "李四 13800000001",          # 追加
    "更新日期":   "2026-08-07"                 # 覆盖
  }
}

写入策略(按 SKILL.md):
  - 客户记录 / 联系人 → 追加(新行加到现有内容底部,mmdd 前缀)
  - 下一步计划 / 下一步行动 / 更新日期 → 覆盖
  - 其他字段 → 不写(留给 customer-update)
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# 统一合并后所有模块同目录,直接把脚本目录加入 sys.path 即可互相 import
sys.path.insert(0, str(Path(__file__).parent))

from kdocs_client import (
    find_customer_rows,
    get_row,
    update_cells,
    KdocsError,
)
from field_defs import (
    FIELD_TO_COL,
    SINGLE_VALUE_FIELDS,
    MULTILINE_FIELDS,
)

# customer-record 管辖的列(销售内部字段)
RECORD_FIELDS = {"客户记录", "下一步计划", "下一步行动", "联系人", "更新日期"}
# 追加型字段(新值加到现有内容底部)
APPEND_FIELDS = {"客户记录", "联系人"}


def today_str() -> str:
    """今天 YYYY-MM-DD"""
    return datetime.now().strftime("%Y-%m-%d")


def mmdd_prefix() -> str:
    """当前月日 mmdd(用于客户记录前缀)"""
    return datetime.now().strftime("%m%d")


def find_customer(customer_name: str) -> int:
    """
    找客户行号(0-based)。命中 1 行返回 row,多行报错,0 行报错。
    """
    matches = find_customer_rows(customer_name, col=0)
    if not matches:
        raise KdocsError(f"客户「{customer_name}」在 Excel 中不存在,要不要新增?(→ customer-update)")
    if len(matches) > 1:
        names = "\n  ".join(f"行 {m['row'] + 1}: {m['value']}" for m in matches)
        raise KdocsError(
            f"命中 {len(matches)} 个同名客户,请用更精确的关键词:\n  {names}"
        )
    return matches[0]["row"]


def _resolve_overwrite(field: str) -> bool:
    """环境变量 CUSTOMER_RECORD_OVERWRITE 控制哪些字段走覆盖而非追加。
    用法:CUSTOMER_RECORD_OVERWRITE=客户记录,联系人 python3 record.py '...'
    """
    import os
    env = os.environ.get("CUSTOMER_RECORD_OVERWRITE", "")
    if not env:
        return False
    fields = {f.strip() for f in env.split(",")}
    return field in fields


def build_updates(row: int, writes: dict) -> list[dict]:
    """
    根据 writes 字典构造 update_cells 的 cells 数组。
    处理策略:
      - 追加型字段:读现有内容 + "\n" + 新值
      - 覆盖型字段:直接用新值
    """
    # 先读整行
    cells = get_row(row, 0, 21)
    current = {c["col"]: c["value"] for c in cells}

    updates = []
    for field, new_val in writes.items():
        if field not in RECORD_FIELDS:
            print(f"⚠️ 字段「{field}」不在 customer-record 管辖范围,跳过(留给 customer-update)")
            continue
        if not new_val or not str(new_val).strip():
            print(f"⏭ 「{field}」新值为空,跳过")
            continue

        col_1based = FIELD_TO_COL.get(field)
        if not col_1based:
            print(f"⚠️ 字段「{field}」找不到列号,跳过")
            continue

        col_0based = col_1based - 1
        cur_val = (current.get(col_0based) or "").strip()

        if field in APPEND_FIELDS and not _resolve_overwrite(field):
            # 追加型:拼接现有内容 + 新值
            if field == "客户记录":
                new_line = f"{mmdd_prefix()} {new_val.strip()}"
            else:
                new_line = new_val.strip()
            if cur_val:
                final = f"{cur_val}\n{new_line}"
            else:
                final = new_line
        else:
            # 覆盖型(覆盖字段 或 环境变量强制覆盖)
            final = str(new_val).strip()

        updates.append({"row": row, "col": col_0based, "value": final})

    # 自动写 更新日期(如果用户没指定)
    if "更新日期" not in writes:
        col_0based = FIELD_TO_COL["更新日期"] - 1
        updates.append({"row": row, "col": col_0based, "value": today_str()})

    return updates


def main():
    parser = argparse.ArgumentParser(
        description="customer-record: 把销售跟进信息写入云端 Excel 的销售内部字段",
    )
    parser.add_argument(
        "payload", nargs="?",
        help='JSON 字符串,格式见 SKILL.md(或用 --stdin 从 stdin 读)',
    )
    parser.add_argument(
        "--stdin", action="store_true",
        help="从 stdin 读 JSON payload",
    )

    args = parser.parse_args()

    if args.stdin:
        payload = json.loads(sys.stdin.read())
    elif args.payload:
        payload = json.loads(args.payload)
    else:
        print("❌ 必须提供 payload(JSON 字符串)或用 --stdin", file=sys.stderr)
        sys.exit(1)

    customer_name = payload.get("customer_name") or payload.get("customer")
    writes = payload.get("writes", {})

    if not customer_name:
        print("❌ payload 缺少 customer_name", file=sys.stderr)
        sys.exit(1)
    if not writes:
        print("❌ payload 缺少 writes", file=sys.stderr)
        sys.exit(1)

    print(f"📋 客户: {customer_name}")
    print(f"📝 写入: {list(writes.keys())}\n")

    try:
        row = find_customer(customer_name)
    except KdocsError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(2)

    print(f"✅ 命中行 {row + 1}")

    updates = build_updates(row, writes)
    if not updates:
        print("❌ 没有可写入的内容")
        sys.exit(3)

    print("\n📋 预览:")
    for u in updates:
        col_1based = u["col"] + 1
        field_name = next((f for f, c in FIELD_TO_COL.items() if c == col_1based), "?")
        val_preview = u["value"]
        if len(val_preview) > 80:
            val_preview = val_preview[:80] + "..."
        print(f"  col {col_1based} ({field_name}): {val_preview}")

    print("\n💾 写入云端 Excel...")
    try:
        result = update_cells(updates)
        print(f"✅ 写入成功(改了 {len(updates)} 个 cell)")
        print(f"\n💡 需要 vault 同步吗?(手动触发 customer-vault,默认不用)")
    except KdocsError as e:
        print(f"❌ 写入失败: {e}", file=sys.stderr)
        sys.exit(4)


if __name__ == "__main__":
    main()
