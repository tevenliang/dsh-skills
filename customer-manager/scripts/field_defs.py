"""
22 Excel 列字段定义 —— 单一派生自 shared_map.FIELD_DEFS。

shared_map.FIELD_DEFS 是 22 字段唯一真源（含 Excel 列号 / 表头 / vault frontmatter key / 是否多行）。
本模块只做"从真源派生"的便捷查表 + 分类，杜绝两份定义分叉。

注意：
- 这里只定义 Excel 列顺序 + 表头名（用于读 Excel 和格式化输出）
- 不包含 vault frontmatter key 映射（那是 shared_map 的事）
- 不包含 vault 专属字段（如"关联issue"）
"""

from shared_map import FIELD_DEFS

# (excel_col_1based, excel_header) —— 表头取自 FIELD_DEFS 第 2 字段
EXCEL_FIELDS = [(col, header) for col, header, key, ml in FIELD_DEFS]

# 列号 → 字段名
COL_TO_FIELD = {col: name for col, name in EXCEL_FIELDS}

# 字段名 → 列号
FIELD_TO_COL = {name: col for col, name in EXCEL_FIELDS}

# 总列数
TOTAL_COLS = len(EXCEL_FIELDS)


def get_field_name(col_1based: int) -> str:
    """根据 1-based 列号获取字段名（无则返回空字符串）"""
    return COL_TO_FIELD.get(col_1based, "")


def get_col_1based(field_name: str) -> int:
    """根据字段名获取 1-based 列号（无则返回 0）"""
    return FIELD_TO_COL.get(field_name, 0)


# 单值字段（不可追加，只能覆盖）—— 由 FIELD_DEFS is_multiline 派生
SINGLE_VALUE_FIELDS = {name for col, name, key, ml in FIELD_DEFS if not ml}

# 多行字段（可追加）
MULTILINE_FIELDS = {name for col, name, key, ml in FIELD_DEFS if ml}

# 校验：单值 + 多行 = 全部 22 字段
assert SINGLE_VALUE_FIELDS | MULTILINE_FIELDS == set(name for _, name in EXCEL_FIELDS), \
    "字段分类有遗漏"
