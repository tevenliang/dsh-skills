from __future__ import annotations
#!/usr/bin/env python3
"""
customer-vault CLI: 读云端 Excel → 写 vault md(单向)

用法:
  python3 sync.py '<客户名>'                    # 单客户
  python3 sync.py --all                        # 全部客户
  python3 sync.py --all --industry 互联网       # 按行业筛选

路径:
  ~/Documents/steven_vault/11_customer/客户资料/{客户名称}.md

设计:
  - Excel header → vault frontmatter key 的映射用 scripts/shared_map.py(v2.8 起内嵌,自包含)
  - 多行字段(联系人/跟进记录/公司简介 等)直接保留换行(YAML 用 | 块标量或单引号字符串)
  - 已存在文件:只覆盖 frontmatter,保留章节内容(避免破坏手动维护的笔记)
  - 备注字段不写入 fm(已迁到正文段 ## 7. 备注,v2.7 规范)
  - 新建文件:含完整章节模板
"""

import argparse
import re
import os
import sys
from datetime import datetime
from pathlib import Path

# 统一合并后所有模块同目录,直接把脚本目录加入 sys.path 即可互相 import
sys.path.insert(0, str(Path(__file__).parent))

from kdocs_client import (
    find_customer_rows,
    get_row,
    get_full_sheet,
    get_file_info,
    FILE_ID,
    KdocsError,
)
import cache  # noqa: E402
from field_defs import FIELD_TO_COL  # noqa: E402
import shared_map  # noqa: E402

# vault 路径
VAULT_ROOT = Path.home() / "Documents" / "steven_vault"
CUSTOMER_DIR = VAULT_ROOT / "11_customer" / "客户资料"
TEMPLATE_PATH = CUSTOMER_DIR / "_templates" / "客户信息模板.md"


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def today_noon_timestamp() -> float:
    """今天 12:00 的 Unix 时间戳(用于 mtime 同步,避免日期漂移)"""
    return datetime.now().replace(hour=12, minute=0, second=0, microsecond=0).timestamp()


def load_template_body() -> str:
    """读 vault md 模板的章节正文(去掉 frontmatter)"""
    if not TEMPLATE_PATH.exists():
        return "\n# {name}\n"
    text = TEMPLATE_PATH.read_text()
    # 第一个 --- 之后就是正文
    if "---" in text:
        _, _, body = text.partition("---")
        _, _, body = body.partition("---")
        return body.lstrip("\n")
    return text


def split_frontmatter_and_body(text: str) -> tuple[str, str]:
    """
    切 markdown 的 frontmatter 和正文。

    关键:frontmatter 分隔符 --- 必须是 **行首无缩进** 的。
    字段值内嵌的 --- (双向同步时代的转义字符串或块标量里可能有)
    因为有缩进,不会被误切。

    返回 (frontmatter_with_delimiters, body_without_leading_newlines)
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return "", text.lstrip("\n")

    # 找第二个 行首无缩进 ---
    for i in range(1, len(lines)):
        if lines[i].strip() == "---" and lines[i] == lines[i].lstrip():
            fm = "\n".join(lines[:i + 1])
            body = "\n".join(lines[i + 1:]).lstrip("\n")
            return fm, body

    # 整个文件都是 frontmatter(没找到第二个 ---)
    return text, ""


def normalize_cell_value(raw: dict) -> str:
    """
    规范化单元格原始值。

    特殊处理:日期型 + numFormat 仅显示 mm-dd / m-d(缺年份)
    → 用 understandableType.value 完整日期(如 '2026-8-10'),避免 vault 只看到 '08-10' 误判。

    其他情况:用 cellText(已按 numFormat 格式化好的显示值)。
    """
    if not raw:
        return ""
    cell_text = raw.get("cellText") or ""
    num_fmt = (raw.get("numFormat") or "").lower()
    ut = raw.get("understandableType") or {}
    ut_type = ut.get("type")
    ut_value = ut.get("value")

    # 仅 mm-dd / m-d 这种缺年份的日期格式才补全
    DATE_FMTS_NO_YEAR = {"mm-dd", "m-d", "mm/dd", "m/d", "d-m", "dd-mm", "d/m", "dd/mm"}
    if ut_type == "date" and ut_value and num_fmt in DATE_FMTS_NO_YEAR:
        # ut_value 可能是 "2026-8-10" / "2026-08-03" / "2026/8/10",统一成 YYYY-MM-DD
        v = str(ut_value).strip().replace("/", "-")
        m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", v)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return v

    return cell_text


def cell_to_yaml_value(value: str, is_multiline: bool, is_list: bool = False) -> str:
    """cell 文本 → YAML 值"""
    v = (value or "").strip()
    if not v:
        if is_list:
            return "[]"
        return "''"
    # 列表字段:按换行拆 list
    if is_list:
        items = [ln.strip() for ln in v.split("\n") if ln.strip()]
        return "[" + ", ".join(f'"{it}"' for it in items) + "]"
    # 含真换行 → 必须用 | 块标量（单引号包了会丢换行,导致 PyYAML 解析错）
    # 关键修复:即便 is_multiline=False（如地址/网站等"单值"字段）,
    # 只要 Excel 里塞了多行,就要走 | 标量,不能单引号包
    if "\n" in v:
        lines = v.split("\n")
        return "|\n" + "\n".join(f"  {ln}" for ln in lines)
    # 含特殊字符 → 单引号包裹
    # 注意:不能只看"包含",还要看"行首"(YAML 里 - ? * 等只在行首是关键字)
    if any(c in v for c in [":", "#", "{", "}", "[", "]", "&", "*", "|", ">", "%", "@", "`"]):
        return "'" + v.replace("'", "''") + "'"
    # 行首是 YAML 关键字(- ? * & ! | > % @ ` { [ #)→ 单引号包裹
    if v and v[0] in "-?*&!|>%@`{[#":
        return "'" + v.replace("'", "''") + "'"
    return v


def build_frontmatter(cells: list[dict]) -> str:
    """
    把一行 cells 转成 vault frontmatter YAML。
    字段顺序严格按 shared_map.FIELD_DEFS。
    """
    # 用 cellText(显示值)而非 originalCellValue:cellText 已按 numFormat 格式化,
    # 避免日期变成 46237 序列号、避免小数变成 0.0999999 等。
    current = {}
    for c in cells:
        raw = c.get("raw") or {}
        val = normalize_cell_value(raw) or c.get("value") or ""
        current[c["col"]] = val

    lines = ["---"]
    for col_1based, excel_header, fm_key, is_multiline in shared_map.FIELD_DEFS:
        col_0based = col_1based - 1
        val = current.get(col_0based, "")
        is_list = fm_key in shared_map.LIST_KEYS
        yaml_val = cell_to_yaml_value(val, is_multiline, is_list)
        # v2.7 规范:备注字段从 fm 迁到 body "## 7. 备注" 段,不写入 fm
        if fm_key == "备注":
            continue
        lines.append(f"{fm_key}: {yaml_val}")

    # vault 专属键(不在 Excel 22 列中)
    for vk in shared_map.VAULT_KEYS:
        if vk == "关联issue":
            lines.append(f"{vk}: []")
        else:
            lines.append(f"{vk}: ''")

    # tags / 创建日期(给 Obsidian 用)
    lines.append("tags: []")

    lines.append("---")
    return "\n".join(lines)


def write_vault(customer_name: str, cells: list[dict], dry_run: bool = False) -> str:
    """
    写 vault md。
    - 存在 → 只覆盖 frontmatter,保留正文
    - 不存在 → 用模板正文新建
    """
    target = CUSTOMER_DIR / f"{customer_name}.md"
    fm = build_frontmatter(cells)

    if target.exists():
        # 读原文件,只替换 frontmatter(用鲁棒的 split,避免字段值里的 --- 被误切)
        original = target.read_text()
        _, body = split_frontmatter_and_body(original)
        if body:
            new_content = fm + "\n\n" + body
        else:
            new_content = fm + "\n"
        action = "更新 frontmatter"
    else:
        # 新建,用模板正文
        body_tpl = load_template_body()
        body = body_tpl.replace("{name}", customer_name)
        new_content = fm + "\n" + body
        action = "新建"

    if dry_run:
        return f"  [{action}] {target}"

    target.write_text(new_content)
    # 不再调 os.utime:Excel 是唯一真源,vault 是只读衍生品,不需要 mtime 策略
    return f"  [{action}] {target}"


def sync_one(customer_name: str, dry_run: bool = False) -> str:
    """单客户 vault 同步"""
    matches = find_customer_rows(customer_name, col=0)
    if not matches:
        raise KdocsError(f"客户「{customer_name}」在 Excel 中不存在")
    if len(matches) > 1:
        names = "\n  ".join(f"行 {m['row'] + 1}: {m['value']}" for m in matches)
        raise KdocsError(f"命中多个客户:\n  {names}")

    row = matches[0]["row"]
    cells = get_row(row, 0, 21)
    # 用 Excel 标准名作为 vault 文件名(避免用户输入简称导致文件重名/找不到)
    standard_name = matches[0]["value"]
    return write_vault(standard_name, cells, dry_run)


def sync_all(industry: str | None = None, stage: str | None = None,
             dry_run: bool = False) -> list[str]:
    """批量 vault 同步(走全表缓存)"""
    info = get_file_info()
    cells = cache.get_cells(FILE_ID, info["mtime"], info["version"])
    if cells is None:
        print(f"🔄 缓存失效(mtime={info['mtime']}, version={info['version']}),重读 Excel...",
              file=sys.stderr)
        cells = get_full_sheet()
        cache.save(FILE_ID, info["mtime"], info["version"], cells)

    # 按行聚合
    rows_dict: dict[int, list[dict]] = {}
    for c in cells:
        rows_dict.setdefault(c["row"], []).append(c)

    def gv(row_cells, col):
        for c in row_cells:
            if c["col"] == col:
                return (c.get("value") or "").strip()
        return ""

    results = []
    for row_idx in sorted(rows_dict.keys()):
        if row_idx == 0:  # 跳过表头
            continue
        row_cells = rows_dict[row_idx]
        name = gv(row_cells, 0)
        ind = gv(row_cells, 1)
        stg = gv(row_cells, 2)

        if not name:
            continue
        if industry and industry not in ind:
            continue
        if stage and stage not in stg:
            continue

        try:
            r = write_vault(name, row_cells, dry_run)
            results.append(r)
        except Exception as e:
            results.append(f"  ❌ {name}: {e}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="customer-vault: 读云端 Excel → 单向写入 vault md",
    )
    parser.add_argument("customer", nargs="?", help="客户名")
    parser.add_argument("--all", action="store_true", help="同步所有客户")
    parser.add_argument("--industry", help="按行业筛选(配合 --all)")
    parser.add_argument("--stage", help="按销售阶段筛选(配合 --all)")
    parser.add_argument("--dry-run", action="store_true", help="只预览不写")
    args = parser.parse_args()

    if not args.customer and not args.all:
        print("❌ 必须提供客户名 或 --all", file=sys.stderr)
        sys.exit(1)

    if args.all:
        print(f"🔄 批量同步(industry={args.industry or '∅'}, stage={args.stage or '∅'})\n")
        results = sync_all(args.industry, args.stage, args.dry_run)
        for r in results:
            print(r)
        print(f"\n📊 共处理 {len(results)} 个客户")
    else:
        print(f"🔄 同步客户:{args.customer}\n")
        try:
            r = sync_one(args.customer, args.dry_run)
            print(r)
        except KdocsError as e:
            print(f"❌ {e}", file=sys.stderr)
            sys.exit(2)


if __name__ == "__main__":
    main()
