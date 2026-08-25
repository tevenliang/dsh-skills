#!/usr/bin/env python3
"""
shared_map.py — customer-sync v0.3 单一字段映射真源

v0.3 设计：frontmatter 成为 22 个 Excel 列的完整、对称镜像。
所有同步（Excel→Vault / Vault→Excel / 迁移）都从这里取映射，
杜绝 excel2vault / vault2excel 各自维护一份会分叉的隐患。

FIELD_DEFS 顺序 = frontmatter 写入顺序（也是 Vault→Excel 读取顺序）。
"""

import re

# (excel_col_1based, excel_header, frontmatter_key, is_multiline)
# excel_header 必须与 excel_reader.ExcelCustomer 的属性名一致
FIELD_DEFS = [
    (1,  "客户名称",     "客户名称",     False),
    (2,  "行业",         "行业",         False),
    (3,  "销售阶段",     "销售阶段",     False),
    (4,  "客户标签",     "客户标签",     False),
    (5,  "联系人",       "联系人",       True),   # E → ## 2
    (6,  "客户记录",     "跟进记录",     True),   # F → ## 1
    (7,  "文件链接",     "关联文档",     True),   # G → ## 9
    (8,  "下一步计划",   "下一步计划",   False),
    (9,  "下一步行动",   "下一步行动",   False),
    (10, "总结",         "总结",         True),   # J
    (11, "公司简介",     "公司简介",     True),   # K → ## 3
    (12, "产品服务",     "产品服务",     True),   # L → ## 4
    (13, "财务状况",     "财务状况",     True),   # M → ## 5
    (14, "下游",         "客户群体",     True),   # N → ## 6
    (15, "营收",         "营收",         False),
    (16, "人数",         "人数",         False),
    (17, "网站",         "网站",         False),
    (18, "地址",         "地址",         False),
    (19, "竞争对手",     "竞争对手",     False),
    (20, "城市",         "城市",         False),
    (21, "备注", "备注", True),   # U → ## 7（v0.3 起纳入同步；原"企业信息收集"改名）
    (22, "更新日期",     "更新日期",     False),
]

# 快速查表
COL_TO_KEY = {col: key for col, _, key, _ in FIELD_DEFS}
KEY_TO_COL = {key: col for col, _, key, _ in FIELD_DEFS}
MULTILINE_KEYS = {key for _, _, key, ml in FIELD_DEFS if ml}
ALL_KEYS = [key for _, _, key, _ in FIELD_DEFS]

# schema 内以「列表」形式存储的 key（vault frontmatter 存 list，Excel 单元格存换行拼接文本）。
# 关联文档：一个客户可关联多个文档链接（file:// / https），list 更稳，避免多链接挤在一格出错。
LIST_KEYS = {"关联文档"}

# vault 专属键（不进 Excel 22 列），但需保持 frontmatter schema 一致：即使为空也保留。
# 关联issue：客户↔issue 双链列表，空客户也要有此空字段，方便统一填写与反链一致性。
VAULT_KEYS = ["关联issue"]

# dump_frontmatter 时「即使为空也保留」的键集合 = 22 Excel 列 + vault 专属键。
SCHEMA_KEYS = ALL_KEYS + VAULT_KEYS


def to_list(v) -> list:
    """把任意值归一成 list[str]（去空、去首尾空白）。
    - list/tuple → 逐项 str
    - 多行字符串 → 按换行拆分
    供 LIST_KEYS 字段在 Excel(字符串) ↔ Vault(列表) 间转换。"""
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        items = [str(x).strip() for x in v]
    else:
        items = [ln.strip() for ln in str(v).split("\n")]
    return [x for x in items if x]


def list_to_text(v) -> str:
    """list → 换行拼接文本（写回 Excel 单元格用）；标量原样 str。"""
    if isinstance(v, (list, tuple)):
        return "\n".join(str(x).strip() for x in v if str(x).strip())
    return "" if v is None else str(v).strip()


def union_links(*lists, as_markdown: bool = True) -> list:
    """LIST_KEYS 双向镜像：多来源链接按 URL 归一去重合并。

    - 入参可为 list 或换行文本（to_list 归一）
    - 兼容混合格式：vault 存 markdown `[名称](url)`，Excel 存纯 `url`
    - 同 URL 优先保留「具名」display（markdown 中文名），避免丢中文显示名
    - as_markdown=True  → 输出 `[名称](url)`（写 vault，Obsidian 可点中文名）
      as_markdown=False → 输出纯 `url`（写 Excel，WPS 可点）
    """
    best = {}  # url -> display(name)
    for lst in lists:
        for item in to_list(lst):
            s = str(item).strip()
            m = re.match(r"^\[(.*?)\]\((.*?)\)\s*$", s)
            if m:
                name, url = m.group(1).strip(), m.group(2).strip()
            else:
                name = url = s
            if not url:
                continue
            # 同 URL 优先保留具名 display（原纯 url 会被中文名替换）
            if url not in best or (name != url and best[url] == url):
                best[url] = name
    urls = list(best.keys())
    return [f"[{best[u]}]({u})" if as_markdown else u for u in urls]

# 渲染只读正文用的段顺序与标题（方案乙）
# 顺序遵循 vault 既有编号习惯：## 1 跟进记录, ## 2 联系人, ... ## 7 备注, ## 9 关联文档
SECTION_ORDER = [
    "跟进记录", "联系人", "公司简介", "产品服务",
    "财务状况", "客户群体", "备注", "关联文档",
]
SECTION_HEADINGS = {
    "跟进记录":     "## 1. 跟进记录",
    "联系人":       "## 2. 联系人",
    "公司简介":     "## 3. 公司简介",
    "产品服务":     "## 4. 主要产品或服务",
    "财务状况":     "## 5. 财务状况",
    "客户群体":     "## 6. 主要客户群体",
    "备注": "## 7. 备注",
    "关联文档":     "## 9. 关联文档",
}
# 反向：heading 全文 → key（迁移时从旧正文提取用）
HEADING_TO_KEY = {v: k for k, v in SECTION_HEADINGS.items()}

# Obsidian 属性（非 Excel 字段）
EXTRA_KEYS = ["tags", "其他信息"]

# 语义路由：vault 历史存在多套正文段标题体系（标准 / 公司背景+主营产品及服务+…
# / 主营产品/服务+业务规模+… / 公司所属行业+官网+…），用关键词把任意旧标题
# 归并到 22 key 之一；无法归并的（业务挑战/战略/规模/地位/格局/其他）落到
# vault 专属的「其他信息」key，绝不静默丢弃。
HEADING_KEYWORDS = [
    ("竞争对手", "竞争对手"),
    ("主营|产品|服务", "产品服务"),
    ("财务|营收|营业|收入", "财务状况"),
    ("客户|下游|群体", "客户群体"),
    ("背景|简介|概况|基本信息", "公司简介"),
    ("官网|网址|网站", "网站"),
    ("地址|总部", "地址"),
    ("人数|员工", "人数"),
    ("行业", "行业"),
    ("关联文档|链接", "关联文档"),
    ("联系人|法人|董事长|电话|邮箱", "联系人"),
    ("跟进|记录", "跟进记录"),
    ("信息收集|查询|公开信息|备注", "备注"),
    ("总结|summary", "总结"),
    ("下一步|计划", "下一步计划"),
    ("下一步|行动", "下一步行动"),
    ("挑战|战略|规模|地位|格局|其他|备注|信息", "其他信息"),
]


def parse_date(s) -> "object":
    """'2026-07-27' / '2026/07/27' / '2026-07-27 00:00:00' → datetime.date，无法解析返回 None。
    供双向同步按「更新日期」判胜负使用。"""
    import re, datetime
    if not s:
        return None
    t = str(s).strip()
    t = re.sub(r"\s+\d{1,2}:\d{2}:\d{2}.*$", "", t)  # 去时间后缀
    t = t.replace("/", "-")
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except Exception:
        return None


def route_heading(heading: str) -> str:
    """旧正文段标题 → frontmatter key（语义兜底，保证有落点）"""
    h = heading.strip()
    # 1) 精确命中标准标题
    if h in HEADING_TO_KEY:
        return HEADING_TO_KEY[h]
    # 2) 关键词嗅探（标题 + 前 120 字内容）
    import re
    for pat, key in HEADING_KEYWORDS:
        if re.search(pat, h):
            return key
    return "其他信息"  # 兜底，绝不丢


def render_body(fm: dict, name: str) -> str:
    """2026-07-27 设计变更：正文被判定为 frontmatter 的冗余镜像，已全部清空。

    现在恒返回空串——frontmatter 为唯一数据源，所有同步写盘只写 frontmatter，
    不再重建正文。保留此函数仅为向后兼容（迁移/单向脚本仍调用），实际输出恒为空。
    """
    return ""


def ordered_frontmatter(fm: dict) -> "dict":
    """按 FIELD_DEFS 顺序重组 frontmatter（保证写入顺序稳定、可读）。
    同时保留 vault 专属 key（其他信息 等不在 22 字段内的内容），不得丢弃。"""
    out = {}
    for key in ALL_KEYS:
        if key in fm:
            out[key] = fm[key]
    for k, v in fm.items():
        if k not in ALL_KEYS:
            out[k] = v
    return out
