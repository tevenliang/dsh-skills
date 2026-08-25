#!/usr/bin/env python3
"""
feishu_watchlist.py - 读取博主订阅名单 (2026-07-19 起读本地, 不再调飞书)

真相源:
  - 2026-07-19 反转: 用户维护博主清单的"唯一真相源" = vault 根 watchlist.md
    (~/Documents/steven_vault/watchlist.md, git tracked), 不再用飞书文档同步。
  - get_watchlist_markdown() 直接读本地 md, 不再调 lark-cli, 也无需 obj_token。
  - 残留 DEFAULT_DOC / lark-cli 相关代码保留作 fallback, 但默认不走; 如果哪天
    飞书复活, 解开 _run_lark 调用即可。

支持格式 (与历史 watchlist.md 完全兼容):
  ## 平台 (keyword)
  | 博主 | 分类 | url |
  | --- | --- | --- |

本模块被 lib.sh 的 get_active_bloggers / fetch_url.sh 的 parse_douyin_rows 等
复用。
"""

import os
import re
import sys
import time
import subprocess
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
DEFAULT_DOC = "UWvidt2iboUQAVxIzHWcxywQncb"  # Watchlist 关注博主清单(obj_token)

# 短时效缓存: 同一进程多次调用(3 平台 + fetch_url)只打 1 次飞书, 降低频控风险
_CACHE_FILE = SKILL_DIR / "state" / ".watchlist_feishu_cache.md"
_CACHE_TTL = 600  # 秒


def _load_config() -> dict:
    cfg_path = SKILL_DIR / "config.yaml"
    if cfg_path.exists():
        try:
            import yaml
            return yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
    return {}


def watchlist_doc_token() -> str:
    cfg = _load_config()
    tok = (cfg.get("feishu", {}) or {}).get("watchlist_doc")
    return tok or DEFAULT_DOC


def _run_lark(args):
    cmd = ["lark-cli"] + args
    # 复用当前 shell 环境变量(含 HTTPS_PROXY, 飞书经用户正常代理/VPN 可达)
    try:
        res = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("lark-cli 超时(120s)")
    if res.returncode != 0:
        raise RuntimeError(f"lark-cli 失败 rc={res.returncode}: {res.stderr.strip()}")
    return res.stdout


def fetch_raw() -> str:
    """拉取飞书 Watchlist 文档原始 pretty 文本"""
    token = watchlist_doc_token()
    return _run_lark(
        ["docs", "+fetch", "--doc", token, "--as", "user", "--format", "pretty"]
    )


def _cell_text(raw: str) -> str:
    """从 lark-td 内容提取单元格文本。
    若是 markdown 链接 [text](url) → 返回 url(表格 url 列需要裸链接);
    否则返回去多余空白的纯文本。"""
    s = raw.strip()
    m = re.search(r"\[[^\]]*\]\((https?://[^)\s]+)\)", s)
    if m:
        return m.group(1)
    return re.sub(r"\s+", " ", s).strip()


def _reconstruct_markdown(raw: str) -> str:
    """把 lark pretty 文本还原成 markdown 表格 + ## 平台 小节.

    兼容两种 lark 输出格式:
      - 旧 <lark-table>/<lark-tr>/<lark-td> (老版本 lark-cli)
      - 新 <table>/<tr>/<td>/<h2> HTML 标记 (当前 lark-cli 默认 pretty)
    还原结果与旧 watchlist.md 等价, parse_rows/parse_section_rows 无需改动即可复用.
    """
    from html.parser import HTMLParser
    import re as _re

    class _P(HTMLParser):
        """显式状态机: 不依赖栈顶 tag, 避免 <td><p> 嵌套导致漏抓."""
        def __init__(self):
            super().__init__()
            self.state = "NORMAL"   # NORMAL | IN_H2 | IN_CELL
            self.h2_buf = []
            self.cell_buf = []
            self.in_a = False
            self.a_href = None
            self.row_buf = []
            self.cur_table_rows = []
            self.tables = []         # [(h2, rows), ...]
            self.cur_h2 = None

        def handle_starttag(self, tag, attrs):
            attrs_d = dict(attrs)
            # 归一化 lark-cli 自定义标签: <lark-table>/<lark-tr>/<lark-td> → table/tr/td
            if tag.startswith("lark-"):
                tag = tag[5:]
            if tag == "h2":
                self.state = "IN_H2"
                self.h2_buf = []
            elif tag == "table":
                self.cur_table_rows = []
            elif tag == "tr":
                self.row_buf = []
            elif tag in ("td", "th"):
                self.state = "IN_CELL"
                self.cell_buf = []
            elif tag == "a":
                self.in_a = True
                self.a_href = attrs_d.get("href", "") or attrs_d.get("data-href", "")
        def handle_data(self, data):
            if self.state == "IN_H2":
                self.h2_buf.append(data)
            elif self.state == "IN_CELL":
                if self.in_a and self.a_href:
                    # 链接内: 优先用 href (watchlist URL 列格式就是 [URL](URL))
                    self.cell_buf.append(self.a_href)
                    self.a_href = None  # 每个 a 只贡献一次
                else:
                    self.cell_buf.append(data)
            else:
                # NORMAL 状态: 捕获 markdown 形式的 "## 平台" 标题
                # (当前 lark-cli pretty 输出把标题写成 markdown 而非 <h2>)
                m = _re.findall(r"##\s*(.+)", data)
                if m:
                    self.cur_h2 = m[-1].strip()
        def handle_endtag(self, tag):
            if tag.startswith("lark-"):
                tag = tag[5:]
            if tag == "h2":
                txt = _re.sub(r"\s+", " ", "".join(self.h2_buf)).strip()
                if txt:
                    self.cur_h2 = txt
                self.h2_buf = []
                self.state = "NORMAL"
            elif tag == "a":
                self.in_a = False
                self.a_href = None
            elif tag in ("td", "th"):
                text = _re.sub(r"\s+", " ", "".join(self.cell_buf)).strip()
                # 兼容旧 markdown 链接格式 [text](url), 仅取 url
                m = _re.search(r"\[[^\]]+\]\((https?://[^)\s]+)\)", text)
                if m:
                    text = m.group(1)
                self.row_buf.append(text)
                self.cell_buf = []
                self.state = "NORMAL"
            elif tag == "tr":
                if self.row_buf:
                    self.cur_table_rows.append(list(self.row_buf))
                self.row_buf = []
            elif tag == "table":
                if self.cur_table_rows:
                    self.tables.append((self.cur_h2, self.cur_table_rows))
                    self.cur_table_rows = []
                    self.cur_h2 = None
    p = _P()
    p.feed(raw)
    out = []
    for h2, rows in p.tables:
        if h2:
            out.append(f"## {h2}")
            out.append("")
        if not rows:
            continue
        hdr = rows[0]
        out.append("| " + " | ".join(hdr) + " |")
        out.append("| " + " | ".join(["---"] * len(hdr)) + " |")
        for r in rows[1:]:
            if not r or all(not c for c in r):
                continue
            while len(r) < len(hdr):
                r.append("")
            out.append("| " + " | ".join(r[:len(hdr)]) + " |")
        out.append("")
    return "\n".join(out).strip() + "\n"


def get_watchlist_markdown(use_cache: bool = True) -> str:
    """返回 Watchlist markdown 文本(供解析逻辑使用)。

    2026-07-19 脱飞书: 直接读本地 watchlist.md —— vault 根优先($VAULT 双平台回退),
    回退 skill 内 watchlist.md(paths.watchlist())。不再调 lark-cli 拉飞书文档。
    """
    vault_wl = _local_watchlist_vault_path()
    if vault_wl and vault_wl.exists():
        return vault_wl.read_text(encoding="utf-8")
    local = _local_watchlist_path()
    if local and local.exists():
        return local.read_text(encoding="utf-8")
    raise RuntimeError("watchlist.md 不存在 (vault 根 或 skill 内)")


def _local_watchlist_path():
    try:
        from paths import watchlist as _wl
        return _wl()
    except Exception:
        return None


def _local_watchlist_vault_path():
    """vault 根 watchlist.md ($VAULT 双平台回退)。"""
    import os
    from pathlib import Path as _P
    env = os.environ.get("VAULT")
    if env:
        base = _P(env).expanduser()
    else:
        try:
            sysname = os.uname().sysname
        except Exception:
            sysname = "Darwin"
        if sysname == "Linux":
            base = _P("/home/ubuntu/webdav/steven_vault")
        else:
            base = _P.home() / "Documents" / "steven_vault"
    return base / "subscription" / "watchlist.md"


def parse_rows(md: str, plat_keyword: str) -> list:
    """解析还原后的 markdown, 返回 [(url, name, ocr_flag), ...]。

    ocr_flag: watchlist 第4列，OCR=Y 表示该博主笔记需要 OCR。
    旧调用方若只取前两个元素，仍兼容（ocr_flag 放在第3位）。
    """
    rows = []
    current_plat = None
    for ln in md.splitlines():
        s = ln.strip()
        if s.startswith("## "):
            m = re.search(r"\(([\w-]+)\)", s)
            current_plat = m.group(1).lower() if m else None
            continue
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not cells:
            continue
        if all(re.match(r"^-+$", c) for c in cells if c):
            continue
        if "博主" in s and "url" in s.lower():
            continue
        if len(cells) < 3:
            continue
        name, _category, url = cells[:3]
        # 第4列 OCR 标志（仅小红书有效，其他平台默认空）
        ocr_flag = cells[3].strip().upper() == "Y" if len(cells) > 3 else False
        if current_plat is None or plat_keyword not in current_plat:
            continue
        if not url or not url.startswith(("http://", "https://")):
            continue
        rows.append((url, name, ocr_flag))
    return rows


# ── 自定义关注设置(京东/Boss/领英/贴吧) ───────────────────────────────
# 这些平台不是"博主清单", 而是各自的关注配置, 且都是"关键词/条目"型:
#   京东  → 搜索关键词   (## 京东 (jd) 表: | 关键词 | 标签 |)
#   Boss  → 搜索关键词(+城市) (## Boss (boss) 表: | 关键词 | 城市 | 标签 |)
#   领英  → 搜索关键词(+城市) (## 领英 (linkedin) 表: | 关键词 | 城市 | 标签 |)
#   贴吧  → 吧名          (## 贴吧 (tieba) 表: | 吧名 | 备注 |)
# 用户直接在飞书里改关键词, 下一次抓取即用新关键词执行; 变化即时生效。
_HEADER_FIRST = {"关键词", "博主", "吧名", "security_id", "链接", "名称", "id"}


def parse_section_rows(md: str, plat_keyword: str) -> list:
    """返回该 ## 平台 小节下的数据行(不含表头), 每行是 [cell1, cell2, ...]。

    与 parse_rows 不同: 不要求含 url 列, 也不限制列数, 用于抓取自定义配置。
    """
    rows = []
    current = None
    for ln in md.splitlines():
        s = ln.strip()
        if s.startswith("## "):
            m = re.search(r"\(([\w-]+)\)", s)
            current = m.group(1).lower() if m else None
            continue
        if current is None or plat_keyword not in current:
            continue
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not cells:
            continue
        if all(re.match(r"^-+$", c) for c in cells if c):
            continue
        if cells[0] in _HEADER_FIRST:
            continue
        rows.append(cells)
    return rows


def get_platform_items(plat_keyword: str) -> list:
    """返回 parse_section_rows 结果(飞书不可达时回退空列表)。"""
    try:
        return parse_section_rows(get_watchlist_markdown(), plat_keyword)
    except Exception as e:
        sys.stderr.write(f"[feishu_watchlist] 读取 {plat_keyword} 配置失败: {e}\n")
        return []


def get_jd_keywords() -> list:
    """返回 [{'kw':..., 'label':...}, ...]；飞书不可达回退空列表(由调用方兜底默认)。"""
    out = []
    for r in get_platform_items("jd"):
        kw = r[0]
        if not kw:
            continue
        label = r[1] if len(r) > 1 and r[1] else kw
        out.append({"kw": kw, "label": label})
    return out


def get_tieba_forums() -> list:
    """返回 [吧名, ...]；飞书不可达回退空列表(由调用方兜底默认)。"""
    return [r[0] for r in get_platform_items("tieba") if r and r[0]]


def get_boss_keywords() -> list:
    """返回 [{'kw':..., 'city':..., 'label':...}, ...]；飞书不可达回退空列表。

    ## Boss (boss) 表格式: | 关键词 | 城市 | 标签 |
      - kw    = 必填, 搜索职位关键词(如 AIBD / AI销售)
      - city  = 可选, 城市名(如 深圳), 传给 `opencli boss search --city`
      - label = 可选, 展示名(缺省=kw)
    """
    out = []
    for r in get_platform_items("boss"):
        kw = r[0].strip() if r and r[0] else ""
        if not kw:
            continue
        city = r[1].strip() if len(r) > 1 and r[1] else ""
        label = r[2].strip() if len(r) > 2 and r[2] else kw
        out.append({"kw": kw, "city": city, "label": label})
    return out


def get_linkedin_keywords() -> list:
    """返回 [{'kw':..., 'city':..., 'label':...}, ...]；飞书不可达回退空列表。

    ## 领英 (linkedin) 表格式: | 关键词 | 城市 | 标签 |
      - kw   = 必填, 搜索职位关键词
      - city = 可选, location(如 深圳 / Shenzhen), 传给 `opencli linkedin search --location`
      - label= 可选, 展示名(缺省=kw)
    """
    out = []
    for r in get_platform_items("linkedin"):
        kw = r[0].strip() if r and r[0] else ""
        if not kw:
            continue
        city = r[1].strip() if len(r) > 1 and r[1] else ""
        label = r[2].strip() if len(r) > 2 and r[2] else kw
        out.append({"kw": kw, "city": city, "label": label})
    return out


if __name__ == "__main__":
    # 命令行: 默认打印还原后的 markdown; --rows <plat> 打印博主解析结果;
    #          --items <plat> 打印自定义关注配置行(京东/Boss/领英/贴吧)
    if len(sys.argv) > 1 and sys.argv[1] == "--rows":
        pk = sys.argv[2] if len(sys.argv) > 2 else "douyin"
        for u, n in parse_rows(get_watchlist_markdown(), pk):
            print(f"{u}|{n}|{ocr}")
    elif len(sys.argv) > 1 and sys.argv[1] == "--items":
        pk = sys.argv[2] if len(sys.argv) > 2 else "jd"
        for r in get_platform_items(pk):
            print(" | ".join(r))
    else:
        sys.stdout.write(get_watchlist_markdown())
