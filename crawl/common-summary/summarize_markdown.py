"""
common/summarize_markdown.py — 从 md 文件抽 (core, speedread, quotes) 与正文段落

把原 subscription-crawl/scripts/publish_wiki.py 里的
parse_frontmatter / extract_sections / split_paragraphs / parse_abstract / _extract_label
提炼为独立可复用模块, 避免 push_to_feishu.py 复制粘贴。

约束:
  - 不依赖订阅子脚本, 任何项目都能 from common.summarize_markdown import *
  - 兼容新版 (🎯一句话核心 / ⏳速读 / 💡核心金句) 与旧版 (✳️主题等) 摘要头
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Tuple

import yaml


# ── frontmatter ────────────────────────────────────────────────
def parse_frontmatter(md_path: str | Path) -> dict:
    """解析 md 的 YAML frontmatter; 坏 YAML 回退逐行解析, 不丢内容。"""
    try:
        text = Path(md_path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fm_text = text[3:end]
    fm: dict = {}
    try:
        v = yaml.safe_load(fm_text)
        if isinstance(v, dict):
            fm = v
            return fm
    except Exception:
        pass
    # 回退: 逐行解析
    for line in fm_text.splitlines():
        m = re.match(r"^\s*([\w]+)\s*:\s*(.*)$", line)
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        if v == "" or v == "-":
            fm[k] = "-"; continue
        if v.startswith("[") and v.endswith("]"):
            fm[k] = [x.strip().strip('"\'') for x in v[1:-1].split(",") if x.strip()]
            continue
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
        fm[k] = v
    return fm


# ── 正文抽取 (摘要区 + 转录/正文) ─────────────────────────────
def extract_sections(md_path: str | Path) -> Tuple[str, str]:
    """返回 (abstract, body_text); abstract = 第一个 ## 之前的全部内容."""
    try:
        text = Path(md_path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return "", ""
    if text.startswith("---"):
        try:
            end = text.index("\n---", 3)
            body = text[end + 4:]
        except ValueError:
            body = text
    else:
        body = text

    # 找第一个"实质内容" H2 (排除 ## 总结 - 总结属于 abstract 的一部分, 不算内容边界)
    first_h2 = re.search(r"^##\s(?!总结\b)", body, re.MULTILINE)
    if first_h2:
        abstract = body[:first_h2.start()].strip()
        rest = body[first_h2.start():]
    else:
        abstract = body.strip()
        rest = ""

    transcript = ""
    # 优先匹配 已知 body 章节 (bilibili/抖音/小红书等)
    for pat in (r"^##\s*.*转录", r"^##\s*.*正文", r"^##\s*OCR",
                r"^##\s*.*描述", r"^##\s*.*媒体", r"^##\s*.*图片"):
        m = re.search(pat, rest, re.MULTILINE)
        if m:
            transcript = rest[m.end():].strip()
            break
    # 回退: 任何第一个 ## 之后都是 body (xhs 无 abstract 摘要, 整体就是正文)
    if not transcript and rest.strip():
        first_h2 = re.search(r"^##\s", rest, re.MULTILINE)
        if first_h2:
            transcript = rest[first_h2.start():].strip()
    return abstract, transcript



# 2026-07-20 fix: 兼容三种格式:
#   旧 v1: media/images/<fn> 或 media/media/images/<fn>
#   旧 v2: <note_id>/<fn> (opencli 时代)
#   新 xhs-downloader: images/<fn>
# 任一命中都从正文里抽掉, 由 extract_image_refs 单独处理.
# 2026-07-22 fix: 兼容 platform-prefix hash 文件名形式 (tieba fetcher 写入格式),
# 不识别会让 split_paragraphs 把图片行当正文保留,导致 hot.md 里
# 图片引用残留为 (tieba/<hash>.jpg) 而不是 (../../media/<hash>.jpg)。
# 平台前缀 hash 文件名图片 (tieba fetcher 等写入格式).
_KNOWN_PLATS = "douyin|bilibili|xiaohongshu|tieba|jd|linkedin|boss|wechat"
_IMG_LINE_PATTERN = (
    r"!\[[^\]]*\]\("
    r"(?:\.\./)*media/(?:media/)?images/[^)]+"
    r"|images/[^)]+"
    r"|(?:" + _KNOWN_PLATS + r")/[a-z0-9]{16,}\.(?:jpg|jpeg|png|webp|gif)"
    r"\)|"
    r"<img[^>]*src=[\"\']\.?(?:/)?(?:\.\./)*(?:media|images)/[^\"\']+[\"\'][^>]*>"
)
_IMG_LINE_RE = re.compile(_IMG_LINE_PATTERN, re.I)

def split_paragraphs(text: str) -> list[str]:
    """正文拆段 (≈段落级), 单段 ≤ 220 字; 超长按句切分; 无标点按 200 字兜底.

    v2: 跳过 image markdown 行 (由 extract_image_refs 单独处理), 保持 image 完整.
    """
    text = (text or "").strip()
    if not text:
        return []
    text = re.sub(r"^\s*\(来源[:：][^\n]*\)\s*", "", text)
    # 去掉所有 image 行 (含整行只有 image 的)
    cleaned_lines = []
    for ln in text.splitlines():
        if _IMG_LINE_RE.search(ln):
            continue
        # 去掉行内嵌的 image (少见但有)
        ln2 = _IMG_LINE_RE.sub("", ln).strip()
        if ln2:
            cleaned_lines.append(ln2)
        else:
            cleaned_lines.append("")  # 保留空行作段分隔
    text = "\n".join(cleaned_lines)
    raw = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out: list[str] = []
    for p in raw:
        # 跳过 H2 标题行 (如 "## 图片", "## 描述" 等)
        if re.match(r"^##\s", p):
            continue
        if len(p) <= 220:
            out.append(p); continue
        sents = re.split(r"(?<=[。！？!?；;])", p)
        if len(sents) > 1:
            buf = ""
            for s in sents:
                buf += s
                if len(buf) >= 120:
                    out.append(buf.strip())
                    buf = ""
            if buf.strip():
                out.append(buf.strip())
        else:
            for i in range(0, len(p), 200):
                chunk = p[i:i+200].strip()
                if chunk:
                    out.append(chunk)
    return [p for p in out if len(p.strip()) >= 2]


# Image 引用抽取: ![...](media/media/images/...) 或 <img src="media/images/...">


def extract_image_refs(text: str) -> list[dict]:
    """从 md 文本抽图片引用, 关联 after_para (前文最后一段文字).

    返回 [{"path": "media/images/...", "width": 0, "after_para": "..."}, ...]
    """
    if not text:
        return []
    IMG_MD = re.compile(r"!\[[^\]]*\]\((?:\.\./)*(?:media/)?([^)]+)\)")
    IMG_HTML = re.compile(r"<img[^>]*src=[\"\']\.?/?(?:\.\./)*(?:media|images)/[^\"\']+[\"\'][^>]*>", re.I)
    WIDTH = re.compile(r"width=[\"\']?(\d+)", re.I)
    out: list[dict] = []
    last_para = ""
    buf: list[str] = []

    def flush():
        nonlocal last_para
        if buf:
            last_para = " ".join(b.strip() for b in buf if b.strip())[:200]
            buf.clear()

    for ln in text.splitlines():
        m = IMG_MD.search(ln) or IMG_HTML.search(ln)
        if m:
            flush()
            path = m.group(1)
            wm = WIDTH.search(ln)
            w = 0
            if wm:
                try: w = int(wm.group(1))
                except: w = 0
            out.append({"path": path, "width": w, "after_para": last_para})
        elif ln.strip() and not ln.strip().startswith("#"):
            buf.append(ln)
        else:
            flush()
    flush()
    return out





# ── 摘要区解析 → core / speedread / quotes ────────────────────
def _extract_label(text: str, label: str, stop_labels: list[str]) -> str:
    # 兼容标签后 中文/英文 冒号 + 换行 (eg "🎯 一句话核心：\nxxx")
    m = re.search(r"(?:##\s*)?" + re.escape(label) + r"\s*[:：]?\s*\n", text)
    if not m:
        m = re.search(r"[🎯⏳💡]\s*" + re.escape(label) + r"\s*[:：]?\s*\n", text)
    if not m:
        return ""
    start = m.end()
    if stop_labels:
        pat = r"\n(?:##\s*|[🎯⏳💡]\s*(?:" + "|".join(re.escape(x) for x in stop_labels) + r")\s)"
        stop = re.search(pat, text[start:])
        end = start + stop.start() if stop else len(text)
    else:
        end = len(text)
    return text[start:end].strip()


def parse_abstract(abstract: str) -> Tuple[str, str, list[str]]:
    """从 abstract 块 (含 🎯/⏳/💡 头) 抽出 (core, speedread, quotes)."""
    norm: list[str] = []
    for ln in abstract.splitlines():
        s = ln.strip()
        s = re.sub(r"^>\s?", "", s)
        s = s.replace("**", "").replace("__", "")
        norm.append(s)
    text = "\n".join(norm)

    core = _extract_label(text, "一句话核心", ["速读", "线性时间线速读", "核心金句", "金句"])
    speedread = _extract_label(text, "速读", ["核心金句", "金句"])
    if not speedread:
        speedread = _extract_label(text, "线性时间线速读", ["核心金句", "金句"])
    quotes_raw = _extract_label(text, "核心金句", [])
    if not quotes_raw:
        quotes_raw = _extract_label(text, "金句", [])
    quotes: list[str] = []
    for q in quotes_raw.splitlines():
        q = re.sub(r"^\s*[\d]+[.．、]\s*", "", q).strip().strip('"').strip()
        if q and q != "无":
            quotes.append(q)
    return core, speedread, quotes


# ── 工具: 把元数据转字符串 ─────────────────────────────────────
def _as_str(v) -> str:
    if v is None: return ""
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else str(v)
    return str(v).strip()


def _publish_date(fm: dict, md_path: Path) -> str:
    # 2026-07-22: 增加 publish_time_raw 支持 (xhs-downloader 落盘格式:
    # "2026-03-13_16:43:36", 用 _ 分隔日期和时间).
    for key in ("publish_time", "created", "publish_time_raw"):
        v = fm.get(key)
        if v is None: continue
        s = v.isoformat() if isinstance(v, (datetime, date)) else str(v)
        # 兼容 "YYYY-MM-DD_HH:MM:SS" 格式 (把 _ 换成空格不影响 [:10] 切片)
        s = s.replace("_", " ", 1) if "_" in s[:10] else s
        if len(s) >= 10:
            d = s[:10].replace("-", "")
            if d.isdigit():
                return d
    try:
        from datetime import timezone, timedelta
        TZ = timezone(timedelta(hours=8))
        t = Path(md_path).stat().st_mtime
        return datetime.fromtimestamp(t, tz=TZ).strftime("%Y%m%d")
    except Exception:
        return "未知日期"


# ── 主接口 ────────────────────────────────────────────────────
def _extract_table_items(md_path: str | Path, fm: dict) -> list[dict]:
    """从 md 第一个"## 职位列表/结果列表/帖子列表/作品列表/笔记列表/视频列表/商品列表"大表格抽多行 → 多 item.

    支持搜索型平台 (linkedin/jd/boss/tieba) 的搜索结果 notes:
      frontmatter 描述搜索元信息, 表格逐行列出职位/帖子. 每行 → 1 个 item,
      title=职位/帖子名(去掉标题污染的 #), source_url=cell 内 markdown 链接,
      author=关键词(搜索型用关键词当作者), publish_date=发布日期列.
    """
    p = Path(md_path)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    # 找 ## 职位列表 / 结果列表 / 帖子列表 / 作品列表 / 笔记列表 / 视频列表 / 商品列表
    list_h2 = re.search(
        r"^##\s*(职位列表|结果列表|帖子列表|作品列表|笔记列表|视频列表|商品列表)\s*$",
        text, re.MULTILINE)
    if not list_h2:
        return []
    # 在 H2 之后找第一个 markdown 表格 (header + sep + 至少 1 行)
    rest = text[list_h2.end():]
    table_match = re.search(
        r"\n(\|[^\n]+\|\n\|[-:\s|]+\|\n(?:\|[^\n]+\|\n?)+)", rest)
    if not table_match:
        return []
    lines = table_match.group(1).strip().splitlines()
    header = [h.strip() for h in lines[0].strip("|").split("|")]
    n_header = len(header)
    rows: list[list[str]] = []
    for line in lines[2:]:
        cells = [c.strip() for c in line.strip("|").split("|")]
        # 容忍 cell 内的 | 分隔符 (jd title 经常含未转义 |): 溢出部分并入 title cell
        if len(cells) > n_header:
            title_cell = " | ".join(cells[1:-(n_header-2)])
            cells = [cells[0], title_cell] + cells[-(n_header-2):]
        if len(cells) == n_header:
            rows.append(cells)
    if not rows:
        return []
    # 列索引
    def find_col(*keywords):
        for i, h in enumerate(header):
            for k in keywords:
                if k in h:
                    return i
        return None
    title_col = find_col("职位", "标题", "结果", "帖子", "作品", "笔记", "视频", "商品") or 0
    location_col = find_col("地点", "城市", "位置")
    date_col = find_col("发布", "时间", "日期")
    company_col = find_col("公司")
    # author: 搜索型用关键词
    base_author = (_as_str(fm.get("author"))
                   or _as_str(fm.get("linkedin_keyword"))
                   or _as_str(fm.get("keyword"))
                   or _as_str(fm.get("jd_keyword"))
                   or _as_str(fm.get("boss_keyword"))
                   or "未知作者")
    base_publish = _publish_date(fm, p)
    items: list[dict] = []
    for row in rows:
        title_cell = row[title_col]
        m = re.search(r"\[([^\]]+)\]\((https?://[^\)]+)\)", title_cell)
        if m:
            title_text = re.sub(r"^#+\s*", "", m.group(1)).strip()
            source_url = m.group(2)
        else:
            title_text = re.sub(r"^#+\s*", "", title_cell).strip()
            source_url = ""
        location = row[location_col] if location_col is not None and location_col < len(row) else ""
        date_cell = row[date_col] if date_col is not None and date_col < len(row) else ""
        company = row[company_col] if company_col is not None and company_col < len(row) else ""
        # 解析日期 YYYY-MM-DD → YYYYMMDD
        if date_cell and re.match(r"^\d{4}-\d{2}-\d{2}$", date_cell):
            pub_date = date_cell.replace("-", "")
        elif date_cell and re.match(r"^\d{8}$", date_cell):
            pub_date = date_cell
        else:
            pub_date = base_publish
        # author: 关键词 (+ 公司, 如果有)
        author = base_author + (f" · {company}" if company and company != "|" else "")
        items.append({
            "title": title_text,
            "author": author,
            "publish_date": pub_date,
            "core": "",
            "speedread": "",
            "quotes": [],
            "body_paragraphs": [],
            "source_url": source_url,
            "abstract": "",
        })

    # ── 解析 ## 职位详情 section, 按表格行 idx 挂到 item.body_paragraphs ──
    # 现状 (2026-07-15): tools/linkedin.py v2 在 ## 职位列表 大表格之后追加
    #   ## 职位详情
    #     ### N. <职位标题>
    #       🏢 公司 · 📍 地点 · 🔗 原文链接
    #       **任职要求**:
    #       > ...
    #       **职位描述**:
    #       > ...
    # 这里把每职位的引文段去 `> ` 前缀后, 拼成 body_paragraphs 列表 (推飞书时
    # 会渲染成 v1 设计的 `📖 正文:` 段, 对齐 S7DxwtpRRiCYJekJP37clDugnag 样板).
    detail_blocks = _parse_detail_section(text)
    for idx, paras in detail_blocks.items():
        if 0 <= idx < len(items):
            items[idx]["body_paragraphs"] = paras
    return items


def _parse_detail_section(text: str) -> dict:
    """解析 ## 职位详情 section, 返回 {row_idx_0based: [paragraphs]}.

    每个 `### N.` 块按表格 N-1 行对应; 引文段 `> ...` 去前缀合并为 paragraph.
    """
    out: dict[int, list[str]] = {}
    m = re.search(r"^##\s*职位详情\s*$", text, re.MULTILINE)
    if not m:
        return out
    rest = text[m.end():]
    # 按 ### 数字. 切块 (每个 ### N. <title> 是新职位)
    chunks = re.split(r"\n###\s+(\d+)\.\s+", rest)
    # chunks[0] = H2 段头空白, [1] = "1", [2] = 第一个职位正文, [3] = "2", ...
    for i in range(1, len(chunks), 2):
        idx_str = chunks[i]
        body = chunks[i + 1] if i + 1 < len(chunks) else ""
        try:
            idx = int(idx_str) - 1  # 1-based → 0-based 对应 rows idx
        except ValueError:
            continue
        paragraphs = _detail_body_to_paragraphs(body)
        if paragraphs:
            out[idx] = paragraphs
    return out


def _detail_body_to_paragraphs(body: str) -> list[str]:
    """从 `### N. <title>\n\n🏢 ...\n\n**任职要求**:\n> ...\n\n**职位描述**:\n> ...`
    抽 引文段, 按 (任职要求, 职位描述) 顺序组成 paragraph list.

    每个 section 内的连续 `> ...` 行合成一个 paragraph (保留原文顺序).
    长段 (>500 字) 按句切分; 太短就保留原样.
    """
    paragraphs: list[str] = []
    # 抓 section 标头: **任职要求**: / **职位描述**:
    sections = re.split(r"\*\*\s*(?:任职要求|职位描述)\s*\*\*\s*:?\s*\n", body)
    # sections[0] = 标头前的 meta (公司/地点/链接), 跳过
    # sections[1..] = 每段正文 (引文块)
    for sec in sections[1:]:
        # 截断到下一个 ## 或 ### 之前 (保留单职位内的内容)
        sec = re.split(r"\n###\s+\d+\.", sec, maxsplit=1)[0]
        sec = re.split(r"\n##\s", sec, maxsplit=1)[0]
        # 抽所有 > 引用行, 拼成段
        quoted = []
        for ln in sec.splitlines():
            ln = ln.rstrip()
            if ln.startswith("> "):
                quoted.append(ln[2:])
            elif ln.startswith(">"):
                quoted.append(ln[1:].lstrip())
            elif ln.startswith("*(共") and ln.endswith(")*)"):
                # 截断说明行 (例如 "*(共 8000 字, 已截断前 6000 字)*")
                quoted.append(ln)
        text = " ".join(q.strip() for q in quoted if q.strip())
        if not text:
            continue
        # 长段按句切
        if len(text) > 500:
            sents = re.split(r"(?<=[。！？!?\n])\s*", text)
            buf = ""
            for s in sents:
                buf += s
                if len(buf) >= 200:
                    p = buf.strip()
                    if p and len(p) >= 2:
                        paragraphs.append(p)
                    buf = ""
            if buf.strip():
                p = buf.strip()
                if len(p) >= 2:
                    paragraphs.append(p)
        else:
            paragraphs.append(text)
    return paragraphs


def build_note_blocks(md_path: str | Path) -> list[dict]:
    """从 md 文件读出结构化数据列表, 供 push_aggregated_batch 推 hot doc.

    返回 list[dict]:
      - 1 篇笔记(无大表格) → 1 个 item (build_note_block 行为)
      - 含职位/结果/帖子/作品/笔记/视频/商品列表大表格 → 每行 1 个 item
    """
    p = Path(md_path)
    fm = parse_frontmatter(p)
    table_items = _extract_table_items(p, fm)
    if table_items:
        return table_items
    return [build_note_block(p)]


def build_note_block(md_path: str | Path) -> dict:
    """从 md 文件读出结构化数据, 供 push_to_feishu push_aggregated() 组章节.

    返回 dict:
      {
        "title": "...",       # 文章标题
        "author": "...",      # 博主
        "publish_date": "YYYYMMDD",
        "core": "...",
        "speedread": "...",
        "quotes": [...],
        "body_paragraphs": [...],
        "source_url": "...",
        "abstract": "...",   # 原始 abstract 文本 (empty if not present)
      }
    """
    p = Path(md_path)
    fm = parse_frontmatter(p)
    abstract, transcript = extract_sections(p)

    title = (_as_str(fm.get("title")) or _as_str(fm.get("jd_title"))
             or _as_str(fm.get("name")))
    title = re.sub(r"#\S+", "", title).strip()
    if not title:
        title = re.sub(r"^\d{4}[_-]", "", p.stem).strip() or "(无标题)"

    author = (_as_str(fm.get("author")) or "未知作者")

    source_url = (_as_str(fm.get("source_url")) or _as_str(fm.get("jd_source_url"))
                  or _as_str(fm.get("url")))
    core, speedread, quotes = parse_abstract(abstract) if abstract.strip() else ("", "", [])
    paragraphs = split_paragraphs(transcript)
    image_refs = extract_image_refs(abstract + "\n" + transcript)

    return {
        "title": title,
        "author": author,
        "publish_date": _publish_date(fm, p),
        "core": core,
        "speedread": speedread,
        "quotes": quotes,
        "body_paragraphs": paragraphs,
        "image_refs": image_refs,
        "source_url": source_url,
        "abstract": abstract,
    }


def render_note_markdown(block: dict) -> str:
    """把 build_note_block() 的 dict 渲染成 markdown 章节段.

    H1 = 文章标题, H2 = 一句话核心 / 速读 / 正文 / 金句.
    与 render_aggregated_markdown 的 H1=日期/H2=作者/H3=标题 体系对齐:
    单篇独立文档: H1=标题(顶), H2=各段落.
    """
    lines: list[str] = [f"# {block['title']}", ""]
    meta: list[str] = []
    if block.get("publish_date"):
        d = block["publish_date"]
        if d.isdigit() and len(d) == 8:
            meta.append(f"📅 发布 {d[:4]}-{d[4:6]}-{d[6:]}")
        else:
            meta.append(f"📅 发布 {d}")
    if meta:
        lines.append(" · ".join(meta))
    if block.get("source_url"):
        lines.append(f"🔗 原文链接: {block['source_url']}")

    # 一句话核心
    if block.get("core"):
        lines += ["", "## 一句话核心", block["core"]]

    # 核心金句
    if block.get("quotes"):
        lines += ["", "💡 核心金句："]
        for q in block["quotes"][:3]:
            lines.append(f"· {q}")

    # 速读
    if block.get("speedread"):
        lines += ["", "## 速读"]
        for sl in block["speedread"].split("\n"):
            sl = sl.strip()
            if sl:
                lines.append(sl)

    # 正文
    if block.get("body_paragraphs"):
        lines += ["", "## 正文"]
        for p in block["body_paragraphs"]:
            lines.append(p)

    lines.append("")
    return "\n".join(lines)


# ── 持久型平台 docx 渲染 (每个平台一份, 永久累积, 按 publish_date 分段) ──
def render_aggregated_markdown(items: list[dict], fmt: str = "xml") -> str:
    """按用户最新设计输出整份"持久型"平台 docx.

    用户需求 (2026-07-10 03:13):
      一份 docx = 一个平台 (永久累积, 标题 = 平台名)
      内容按 publish_date 分段:
        H1 = 日期 (YYYY-MM-DD)
          H2 = 作者
            H3 = 文章标题
              📅 发布 / 🔗 原文链接
              🎯 一句话核心
              💡 核心金句
              ⏳ 速读
              📖 正文
            ---
          H2 = 下一作者
        ...
      H1 = 下一日期
        ...

    items: list of dict (build_note_block 输出或同等结构):
      - title, author, publish_date, source_url
      - core, speedread, quotes, body_paragraphs
    按 publish_date DESC → author ASC → title ASC 排序 (最新在最前, 同日内 仍按作者/标题升序),
    同 date 同 author 自动合并.
    fmt: 'xml' (送 lark-cli --doc-format xml) 或 'markdown'
    """
    # 日期段是最外层 (H1), 反转排序: 在日期层级倒序; 缺日期的排到最后
    def _date_key(d: str) -> tuple:
        if not d or not (len(d) == 8 and d.isdigit()):
            return (1, "")  # 未知日期放最后
        return (0, -int(d))  # 用负号让升序排为降序

    items_sorted = sorted(
        items,
        key=lambda x: (
            _date_key(x.get("publish_date") or ""),
            (x.get("author") or ""),       # 同日 author 升序
            (x.get("title") or "")          # 同日同作者 title 升序
        )
    )

    is_xml = (fmt == "xml")
    out: list[str] = []
    cur_date = None
    cur_author = None

    def esc(s: str) -> str:
        if s is None: return ""
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    for it in items_sorted:
        date = (it.get("publish_date") or "").strip()
        author = ((it.get("author") or "未知作者").strip() or "未知作者")
        title = ((it.get("title") or "(无标题)").strip() or "(无标题)")
        source_url = (it.get("source_url") or "").strip()
        core = (it.get("core") or "").strip()
        speedread = (it.get("speedread") or "").strip()
        quotes = [str(q).strip() for q in (it.get("quotes") or []) if str(q or "").strip()]
        paras = [str(p).strip() for p in (it.get("body_paragraphs") or []) if str(p or "").strip()]
        publish_label = f"{date[:4]}-{date[4:6]}-{date[6:]}" if (len(date) == 8 and date.isdigit()) else (date or "未知日期")

        # === 日期段 (H1) ===
        if date != cur_date:
            cur_date = date
            cur_author = None
            if out:
                out.append("")  # blank line separator
            if is_xml:
                out.append(f"<h1>{esc(publish_label)}</h1>")
            else:
                out.append(f"# {publish_label}")
            out.append("")

        # === 作者段 (H2) ===
        if author != cur_author:
            cur_author = author
            if is_xml:
                out.append(f"<h2>{esc(author)}</h2>")
            else:
                out.append(f"## {author}")
            out.append("")

        # === 文章 (H3) ===
        if is_xml:
            out.append(f"<h3>{esc(title)}</h3>")
        else:
            out.append(f"### {title}")
        out.append("")

        # === 元数据段 (paragraph) ===
        meta_bits: list[str] = []
        if date:
            meta_bits.append(f"📅 发布 {publish_label}")
        if source_url:
            meta_bits.append(f"🔗 原文链接: {source_url}")
        if meta_bits:
            line = " · ".join(meta_bits)
            if is_xml:
                out.append(f"<p>{esc(line)}</p>")
            else:
                out.append(line)
            out.append("")

        # === 一句话核心 ===
        if core:
            if is_xml:
                out.append("<p>🎯 一句话核心：</p>")
                out.append(f"<p>{esc(core)}</p>")
            else:
                out.append("🎯 一句话核心：")
                out.append(core)
            out.append("")

        # === 核心金句 ===
        if quotes:
            if is_xml:
                out.append("<p>💡 核心金句：</p>")
                for q in quotes[:5]:
                    out.append(f"<p>· {esc(q)}</p>")
            else:
                out.append("💡 核心金句：")
                for q in quotes[:5]:
                    out.append(f"· {q}")
            out.append("")

        # === 速读 ===
        if speedread:
            if is_xml:
                out.append("<p>⏳ 速读：</p>")
                for sl in speedread.split("\n"):
                    sl = sl.strip()
                    if sl:
                        out.append(f"<p>{esc(sl)}</p>")
            else:
                out.append("⏳ 速读：")
                for sl in speedread.split("\n"):
                    sl = sl.strip()
                    if sl:
                        out.append(f"  {sl}")
            out.append("")

        # === 正文 ===
        if paras:
            if is_xml:
                out.append("<p>📖 正文：</p>")
                for p in paras:
                    out.append(f"<p>{esc(str(p))}</p>")
            else:
                out.append("📖 正文：")
                for p in paras:
                    out.append(p)
            out.append("")

        # === 图片 (2026-07-20) ===
        # image_refs 由 publish_vault._materialize_item_images 提前物化到 vault/media,
        # path 已改写为 vault 相对 ("../../media/<hash>.<ext>"). 这里直接渲染.
        item_image_refs = it.get("image_refs") or []
        if item_image_refs:
            if is_xml:
                out.append("<p>🖼️ 图片：</p>")
                for ir in item_image_refs:
                    p = ir.get("path", "")
                    w = ir.get("width", 0)
                    attrs = f' src="{esc(p)}"'
                    if w:
                        attrs += f' width="{w}"'
                    out.append(f"<img{attrs}/>")
            else:
                out.append("🖼️ 图片：")
                for ir in item_image_refs:
                    p = ir.get("path", "")
                    if p:
                        out.append(f"![]({p})")
            out.append("")

        # === 文章结束分隔 ===
        if is_xml:
            out.append("<hr/>")
        else:
            out.append("---")
        out.append("")

    return "\n".join(out).rstrip() + "\n"
