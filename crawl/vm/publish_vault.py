"""
publish_vault.py — 博主子目录发布架构 (2026-07-23)

目录结构:
  $VAULT/subscription/
  ├── douyin/
  │   ├── 东方红老陈/
  │   │   ├── 2026-07-23_大反弹马上来.md
  │   │   ├── 2026-07-22_指数不跌为何你亏30%.md
  │   │   └── images/                # 本博主图片（临时，最终→media）
  │   ├── 口罩哥研报60秒/
  │   │   └── ...
  │   └── douyin-hot.md              # 本月索引（引用，非正文）
  ├── bilibili/
  │   ├── 巫师财经/
  │   │   └── ...
  │   └── bilibili-hot.md
  ├── xiaohongshu/
  │   ├── 招财猫养基/
  │   │   └── ...
  │   └── xiaohongshu-hot.md
  ├── 2607douyin.md                  # 月归档索引
  ├── 2607bilibili.md
  └── 2607xiaohongshu.md

hot.md / 月归档文件 = 索引文件，仅引用子目录文件，不存正文。
图片落点按平台隔离：小红书 → media/xhs/（扁平 + 保留 note_id 子目录），其它平台 → media/<plat>/<作者>/；md 全部用 wikilink ![[media/...]] 引用（md 移动也不断链）
"""
import sys as _sys
# (common-publish path removed for VM: transcribe_worker/ocr_daemon import publish_vault directly)



import json, os, re, shutil, hashlib, time
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

TZ = timezone(timedelta(hours=8))
VAULT = Path(os.environ.get("VAULT", "/home/ubuntu/webdav/steven_vault"))

def _vault_base() -> Path:
    """暴露 vault 根路径（供其他模块导入）"""
    return VAULT

SUBSCRIPTION = VAULT / "subscription"
MEDIA = VAULT / "media"
STATE_DIR = Path("/home/ubuntu") / ".agents" / "skills" / "crawl" / "state"
STATE_FILE = STATE_DIR / ".subscription-crawl-cache.json"
MEDIA_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}


# ═══════════════════════════════════════════════════════════════
# 基础路径
# ═══════════════════════════════════════════════════════════════

def _plat_dir(plat: str) -> Path:
    return SUBSCRIPTION / plat

def _author_dir(plat: str, author: str) -> Path:
    author = _sanitize_dirname(author)
    return _plat_dir(plat) / author

def _media_plat_dir(plat: str, author: str) -> Path:
    author = _sanitize_dirname(author)
    return MEDIA / plat / author

def _hot_path(plat: str) -> Path:
    return SUBSCRIPTION / f"{plat}-hot.md"

def _monthly_path(plat: str, yyyymm: str) -> Path:
    return SUBSCRIPTION / f"{yyyymm}{plat}.md"


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _sanitize_dirname(name: str | float) -> str:
    """目录名清理：去掉 #话题标签 + 非法字符"""
    name = _clean_title(name)
    return re.sub(r'[\/:*?"<>|]', '_', name.strip())

# 文件名字节上限：ext4/多数 Linux 文件系统单个文件名上限为 255 字节（非字符）。
# 一个 UTF-8 汉字占 3 字节，纯按字符数截断会漏过超长中文名（曾出 596 字节文件卡死 WebDAV）。
# 这里按字节截断，留足空间给 ".md"(3) 与去重后缀 "_N"，设 200 字节。
MAX_STEM_BYTES = 200

def _truncate_bytes(s: str, max_bytes: int) -> str:
    """按 UTF-8 字节截断字符串，不切断多字节字符。"""
    b = s.encode("utf-8")
    if len(b) <= max_bytes:
        return s
    return b[:max_bytes].decode("utf-8", errors="ignore")

def _sanitize_filename(name: str | float) -> str:
    """文件名清理：去掉 #话题标签 + 非法字符 + 按字节截断（保留日期前缀）"""
    name = str(name) if not isinstance(name, str) else name
    # 先抽日期前缀（文件名可能在头部有 YYYY-MM-DD_ 或 YYYYMMDD_）
    date_prefix = ""
    title_raw = name

    m = re.match(r'^(\d{4}-\d{2}-\d{2})_', name)
    if m:
        date_prefix = m.group(1).replace('-', '') + "_"  # → 20260723_
        title_raw = name[m.end():]
    else:
        m = re.match(r'^(\d{8})_', name)
        if m:
            date_prefix = m.group(1) + "_"
            title_raw = name[m.end():]

    # 清理正文标题（去掉 #话题标签等）
    title_part = _clean_title(title_raw)
    # 拼回去
    result = date_prefix + title_part
    # 最后去掉残留非法字符
    result = re.sub(r'[\\/:*?"<>|]', '_', result)
    # 按 UTF-8 字节截断（文件系统限制 255 字节，留余量取 200）
    if len(result.encode("utf-8")) > MAX_STEM_BYTES:
        # 尽量保留日期前缀，只截标题部分
        budget = MAX_STEM_BYTES - len(date_prefix.encode("utf-8"))
        result = date_prefix + _truncate_bytes(title_part, max(budget, 0))
        result = re.sub(r'[\\/:*?"<>|]', '_', result).rstrip(" _")
    return result

def _clean_title(name: str | float) -> str:
    name = str(name) if not isinstance(name, str) else name
    """去掉 #话题标签、多余空格/下划线，统一空格"""
    # 去掉 #话题标签
    name = re.sub(r'#\S+', '', name)
    # 去掉 emoji
    name = re.sub(r'[𐀀-􏿿]', '', name)
    # 合并多余空格和下划线
    name = re.sub(r'[\s_]+', ' ', name)
    # 去掉首尾空格和非法字符
    name = re.sub(r'^[_\s]+|[_\s]+$', '', name)
    name = re.sub(r'[\/:*?"<>|]', '_', name)
    return name.strip()

def _short_hash(s) -> str:  # bytes or str
    return hashlib.md5(s if isinstance(s, bytes) else s.encode()).hexdigest()[:12]

def _now():
    return datetime.now(TZ)

def _today_str():
    return date.today().isoformat()  # YYYY-MM-DD

def _yyyymm(d: date = None):
    d = d or date.today()
    return d.strftime("%Y%m")

def _to_date_str(v) -> str:
    """各种日期格式统一转 YYYY-MM-DD

    支持:
    - date / datetime 对象 → strftime
    - 纯 8 位数字 YYYYMMDD (例: 20260730, tieba frontmatter 整数 publish_date)
    - YYYY-MM-DD / YYYY_MM_DD / YYYY 年 MM 月 DD 日 等带分隔符
    """
    if hasattr(v, 'strftime'):
        return v.strftime('%Y-%m-%d')
    s = str(v).strip()
    # 纯 8 位数字 YYYYMMDD (tieba frontmatter publish_date: 20260730)
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    # 2026-07-23 / 2026_07_23 / 2026年07月23日
    m = re.search(r"(\d{4})[\-_\s月年](\d{1,2})[\-_\s月年](\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


# ═══════════════════════════════════════════════════════════════
# 状态管理（缓存去重）
# ═══════════════════════════════════════════════════════════════

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"douyin": [], "bilibili": [], "xiaohongshu": []}

def _save_state(state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))

def _is_seen(plat: str, vid: str) -> bool:
    state = _load_state()
    return vid in state.get(plat, [])

def _mark_seen(plat: str, vid: str):
    state = _load_state()
    state.setdefault(plat, [])
    if vid not in state[plat]:
        state[plat].append(vid)
        # 保留最近500条
        state[plat] = state[plat][-500:]
    _save_state(state)


# ═══════════════════════════════════════════════════════════════
# frontmatter 解析
# ═══════════════════════════════════════════════════════════════

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 YAML frontmatter，返回 (fm_dict, body_without_frontmatter)"""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    import yaml
    try:
        fm = yaml.safe_load(text[4:end])
    except Exception:
        fm = {}
    body = text[end + 6:]
    return fm or {}, body

def _strip_frontmatter_body(text: str) -> str:
    """去掉 frontmatter，保留正文"""
    _, body = _parse_frontmatter(text)
    return body.strip()


# ═══════════════════════════════════════════════════════════════
# 图片物化 → media/
# ═══════════════════════════════════════════════════════════════

def _materialize_images(plat: str, author: str, date_str: str,
                        title: str, images_dir: Path) -> dict:
    """把临时 images_dir 中的图片复制到 media/<目标子目录>（保留 images 下相对路径/子目录），
    返回 {原images相对路径(去images前缀): 'media/<目标>/<rel>'}。后续 _rewrite_image_links 转成 wikilink。

    落点规则（平台隔离，避免互相污染）：
      - 小红书 xhs: 扁平 + 保留 note_id 子目录 → media/xhs/<rel>
      - 其它平台: 按 博主 隔离 → media/<plat>/<author>/<rel>
    全部用 wikilink 引用（obsidian 按 vault 解析，md 移动也不断链）。
    """
    if plat == "xiaohongshu":
        media_dir = MEDIA / "xhs"
        prefix = "xhs"
    else:
        media_dir = _media_plat_dir(plat, author)
        prefix = f"{plat}/{_sanitize_dirname(author)}"
    # 2026-08-15 fix: images_dir 缺失时兜底.
    # race 场景下 images_dir 已被 _materialize_images 上次调用 rmtree,
    # 但 media/xhs/ 里仍有本次笔记的图(同 author + title 关键词匹配).
    # 这种情况下从 media/xhs 里按文件名模糊匹配补上 name_map, 至少保证 md 链接被改写正确.
    # 仅在 images_dir 缺失时兜底, 正常路径仍走 images_dir (优先级最高).
    if not images_dir or not images_dir.exists():
        if plat == "xiaohongshu":
            return _materialize_xhs_fallback(media_dir, author, title)
        return {}
    media_dir.mkdir(parents=True, exist_ok=True)

    img_files = [p for p in images_dir.rglob("*")
                 if p.is_file() and p.suffix.lower() in MEDIA_EXTS]
    if not img_files:
        return {}

    name_map = {}
    for img in img_files:
        rel = str(img.relative_to(images_dir))  # 如 '2026-..png' 或 '<noteid>/01.jpg'
        # 归一化：images_dir 若指向 images/ 本身，rel 会带 'images/' 前缀，去掉它
        rel_parts = Path(rel).parts
        if rel_parts and rel_parts[0] == "images":
            rel = str(Path(*rel_parts[1:]))
        if not rel:
            continue
        dest = media_dir / rel
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(img, dest)
        name_map[rel] = f"media/{prefix}/{rel}"
    # 清理临时 images_dir（统一清理，不逐文件删）
    if images_dir and images_dir.exists():
        try:
            shutil.rmtree(images_dir, ignore_errors=True)
        except Exception:
            pass
    return name_map

def _materialize_xhs_fallback(media_dir: Path, author: str, title: str) -> dict:
    """images_dir 已 rmtree 时的兜底: 从 media/xhs 里按 author + 标题 safe_name 搜图.
    只用于 race 场景; 返回的 name_map 缺失 alt 文本 (rewrite 用不到 alt).
    返回 {filename: 'media/xhs/filename'}.

    注意: xhs-downloader 把标题里的 . 等特殊字符转 _, 所以 filename 里是
    '2026-08-14_14.21.16_<author>_<safe_title>_N.png', 必须把 title 也做同样归一化.
    """
    name_map = {}
    if not media_dir.exists():
        return name_map
    import re as _re
    def _safe(s):
        # 镜像 single_extract.py _safe_name: 去掉 r\/:*?"<>|
        return _re.sub(r'[\/:*?"<>|]', '_', s) if s else ''
    keywords = []
    if author:
        keywords.append(author)
    safe_title = _safe(title)[:12] if title else ''
    if safe_title:
        keywords.append(safe_title)
    if not keywords:
        return name_map
    # 2026-08-15 fix: xhs 内部 (非 single_extract._safe_name, 是更下游
    # 生成 filename 的环节) 实际上把所有"非 [\w\u4e00-\u9fff]" 字符
    # 替换为 '_'。所以 title 里 '.' ' ' '｜' '[' 等全部变 '_',
    # 而 single_extract._safe_name 是不做这层归一化的.
    # 修复: 先把 title 也归一化 (只保留下划线/数字/字母/中文), 然后再
    # 用 safe 的 substring 形式匹配.
    def _xhs_normalize(s: str) -> str:
        """镜像 xhs filename 生成: 非 [A-Za-z0-9_中文] → _, 连续 _ 合并."""
        if not s:
            return ""
        out = []
        for ch in s:
            if ch.isalnum() or ch == "_" or "一" <= ch <= "鿿":
                out.append(ch)
            else:
                out.append("_")
        # 合并连续 _
        return _re.sub(r"_", "_", "".join(out)).strip("_")
    fuzzy_patterns = []
    # 防御: 仅 author 没 title 时会误匹配全 author 历史 → 直接放弃 fallback.
    if author and not safe_title:
        return name_map
    for kw in keywords:
        if not kw:
            continue
        normalized = _xhs_normalize(kw)
        if not normalized:
            continue
        # 逐字符 fuzzy: 归一化后的每个字符之间, 都允许 [ _] 间隔插入.
        # 这样能兼容:
        #   1. 8.14 vs 8_14
        #   2. 14基金 vs 14_基金 (filename 在 word 间多塞 _)
        #   3. 连续 _ 也只匹配一个 [ _]
        chars = [_re.escape(c) if not c.isalnum() and "一" <= c <= "鿿" else c
                 for c in normalized]
        pattern = "[ _]*".join(chars)
        fuzzy_patterns.append(_re.compile(pattern))
    matched = []
    for f in media_dir.iterdir():
        if not f.is_file() or f.suffix.lower() not in MEDIA_EXTS:
            continue
        if all(p.search(f.name) for p in fuzzy_patterns):
            matched.append(f.name)
    for fn in matched:
        name_map[fn] = f"media/xhs/{fn}"
    return name_map


def _rewrite_image_links(lines: list, name_map: dict) -> list:
    """把 md 正文中 images/xxx(可含子目录) 替换成 wikilink ![[media/<目标>/xxx]]"""
    if not name_map:
        return lines
    def _rewire(m):
        alt = m.group(1) or ""
        rel = m.group(2)            # images/<rel> 中 <rel> 部分（无 images/ 前缀）
        new_path = name_map.get(rel)
        if not new_path:
            return m.group(0)
        # 统一用 wikilink，obsidian 按 vault 解析，md 移动也不断链
        return f"![[{new_path}]]"
    new_lines = []
    for ln in lines:
        ln2 = re.sub(r"!\[([^[\]]*)\]\(images\/([^)]+)\)", _rewire, ln)
        new_lines.append(ln2)
    return new_lines


def _rewrite_html_img_tags(lines: list, name_map: dict) -> list:
    """把 md 正文中 <img src="images/xxx" ...> HTML 标签替换成 wikilink ![[media/...]]。

    2026-08-15 修复: 微信内核(_wechat_kernel_main.py)生成的是 HTML <img> 标签,
    而 _rewrite_image_links 只处理 Markdown ![...](images/...) 语法, 漏掉 <img> → 链接永远
    指向已被删除的临时 images/ 目录. 这里补齐 HTML 形态.
    """
    if not name_map:
        return lines
    def _rewire(m):
        rel = m.group(1)            # images/<rel> 中 <rel> 部分（无 images/ 前缀）
        new_path = name_map.get(rel)
        if not new_path:
            return m.group(0)
        return f"![[{new_path}]]"
    new_lines = []
    for ln in lines:
        ln2 = re.sub(r'<img\s+[^>]*src="images\/([^"]+)"[^>]*>', _rewire, ln)
        new_lines.append(ln2)
    return new_lines


# ═══════════════════════════════════════════════════════════════
# 写博主子目录文件
# ═══════════════════════════════════════════════════════════════

def _write_author_file(plat: str, author: str, title: str,
                       body_lines: list, date_str: str,
                       source_url: str, img_map: dict) -> Path:
    """写入 subscription/<plat>/<author>/YYYY-MM-DD_title.md，返回文件路径"""
    author_dir = _author_dir(plat, author)
    author_dir.mkdir(parents=True, exist_ok=True)

    # 文件名
    safe_title = _sanitize_filename(title)
    fname = f"{date_str}_{safe_title}.md"
    # crawl 3.1.0 fix: 已存在则直接覆盖（worker 是 handoff 条目的权威发布方，
    # 旧版序号化成 _1.md 会与 16:19 抓出的空壳并存，造成重复且段名混乱）。
    fpath = author_dir / fname

    # 重建正文（去掉 frontmatter，仅正文部分）
    body_text = "\n".join(body_lines).strip()
    # 图片链接重写
    if img_map:
        body_lines2 = _rewrite_image_links(body_lines, img_map)
        body_text = "\n".join(body_lines2).strip()

    # frontmatter
    fm_lines = [
        "---",
        f"title: \"{title}\"",
        f"author: \"{author}\"",
        f"platform: \"{plat}\"",
        f"publish_date: \"{date_str}\"",
        f"created: \"{_now().isoformat()}\"",
    ]
    if source_url:
        fm_lines.append(f"source_url: \"{source_url}\"")
    fm_lines.append("---")
    fm_lines.append("")

    content = "\n".join(fm_lines) + body_text + "\n"
    fpath.write_text(content, encoding="utf-8")
    return fpath


# ═══════════════════════════════════════════════════════════════
# hot.md / 月归档索引更新
# ═══════════════════════════════════════════════════════════════

def _rel_link(plat: str, author: str, fname: str) -> str:
    """返回 Obsidian 相对路径链接"""
    return f"[{fname}]({plat}/{author}/{fname})"

def _update_hot_index(plat: str, author: str, title: str,
                      date_str: str, fname: str, today: date = None):
    """在 hot.md 顶部追加今日该博主新条目（索引引用）"""
    hot = _hot_path(plat)
    today = today or date.today()
    today_iso = today.isoformat()  # YYYY-MM-DD

    # 平台标签
    plat_label = {"douyin": "抖音", "bilibili": "B站",
                  "xiaohongshu": "小红书"}.get(plat, plat)

    # 读取现有内容
    if hot.exists():
        content = hot.read_text(encoding="utf-8")
    else:
        content = f"# {plat_label} 热帖\n> 自动生成 {datetime.now(TZ).strftime('%Y-%m-%d %H:%M')}\n\n"

    lines = content.splitlines()

    # 找或创建今日 H1 section
    def _find_h1_section(lines, target_date):
        for i, ln in enumerate(lines):
            if ln.strip() == f"# {target_date}":
                return i
        return -1

    h1_idx = _find_h1_section(lines, today_iso)

    if h1_idx < 0:
        # 插入到文件开头（跳过标题行后）
        header_end = 0
        for i, ln in enumerate(lines):
            if ln.startswith("# ") and not ln.startswith("# # "):
                header_end = i
                break
        new_section = [
            f"# {today_iso}",
            "",
            f"### {author}",
            f"- [{title}]({plat}/{author}/{fname}) — {datetime.now(TZ).strftime('%H:%M')}",
            "",
        ]
        lines = lines[:header_end + 1] + new_section + lines[header_end + 1:]
    else:
        # 找今日 section 中的博主 H3
        author_h3 = f"### {author}"
        author_idx = -1
        for i in range(h1_idx + 1, len(lines)):
            ln = lines[i].strip()
            if ln.startswith("### ") and ln != author_h3:
                break
            if ln == author_h3:
                author_idx = i
                break

        entry = f"- [{title}]({plat}/{author}/{fname}) — {datetime.now(TZ).strftime('%H:%M')}"
        if author_idx >= 0:
            # 追加到博主名下（找下一 H3 或 section 结尾）
            insert_idx = author_idx + 1
            while insert_idx < len(lines):
                ln = lines[insert_idx].strip()
                if ln.startswith("### ") or (ln.startswith("# ") and not ln.startswith("##")):
                    break
                if ln.startswith("- ["):
                    insert_idx += 1
                    continue
                break
            lines.insert(insert_idx, entry)
        else:
            # 插入新的博主 H3
            insert_idx = h1_idx + 1
            while insert_idx < len(lines):
                ln = lines[insert_idx].strip()
                if ln.startswith("### ") or (ln.startswith("# ") and not ln.startswith("##")):
                    break
                insert_idx += 1
            lines.insert(insert_idx, author_h3)
            lines.insert(insert_idx + 1, entry)
            lines.insert(insert_idx + 2, "")

    hot.write_text("\n".join(lines), encoding="utf-8")

def _update_monthly_index(plat: str, author: str, title: str,
                           date_str: str, fname: str, item_date: date = None):
    """在月归档索引文件中追加条目"""
    yyyymm = _yyyymm(item_date)
    monthly = _monthly_path(plat, yyyymm)
    item_date_obj = item_date or date.today()
    date_h1 = item_date_obj.strftime("%Y-%m-%d")

    if monthly.exists():
        content = monthly.read_text(encoding="utf-8")
    else:
        content = f"# {yyyymm[:4]}年{yyyymm[4:6]}月 {plat}归档\n> 自动生成\n\n"

    lines = content.splitlines()

    # 找日期 H1
    h1_idx = -1
    for i, ln in enumerate(lines):
        if ln.strip() == f"# {date_h1}":
            h1_idx = i
            break

    if h1_idx < 0:
        lines.append(f"# {date_h1}")
        lines.append("")
        lines.append(f"### {author}")
        lines.append(f"- [{title}]({plat}/{author}/{fname})")
        lines.append("")
    else:
        # 追加到日期 section
        author_h3 = f"### {author}"
        author_idx = -1
        for i in range(h1_idx + 1, len(lines)):
            ln = lines[i].strip()
            if ln.startswith("### ") and ln != author_h3:
                break
            if ln == author_h3:
                author_idx = i
                break
        entry = f"- [{title}]({plat}/{author}/{fname})"
        if author_idx >= 0:
            insert_idx = author_idx + 1
            while insert_idx < len(lines):
                ln = lines[insert_idx].strip()
                if ln.startswith("### ") or (ln.startswith("# ") and not ln.startswith("##")):
                    break
                insert_idx += 1
            lines.insert(insert_idx, entry)
        else:
            insert_idx = h1_idx + 1
            while insert_idx < len(lines):
                ln = lines[insert_idx].strip()
                if ln.startswith("### ") or (ln.startswith("# ") and not ln.startswith("##")):
                    break
                insert_idx += 1
            lines.insert(insert_idx, author_h3)
            lines.insert(insert_idx + 1, entry)
            lines.insert(insert_idx + 2, "")

    monthly.write_text("\n".join(lines), encoding="utf-8")


# ═══════════════════════════════════════════════════════════════
# 主入口：单条发布
# ═══════════════════════════════════════════════════════════════

def append_single_to_hot(platform: str, md_path: str | Path,
                         images_dir: str | Path = None,
                         title: str = None, author: str = None,
                         force_overwrite: bool = False) -> tuple:
    """
    发布单条笔记到博主子目录 (2026-08-04 起不再生成 hot/月归档索引)。
    
    流程：
      1. 解析 md frontmatter 提取 title/author/date/source_url
      2. 写文件到 subscription/<plat>/<author>/YYYY-MM-DD_title.md
      3. 图片物化到 media/<plat>/<author>/
    """
    md_p = Path(md_path).resolve()
    if not md_p.exists():
        raise FileNotFoundError(f"md 不存在: {md_p}")

    # 解析 frontmatter
    text = md_p.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)
    body_lines = body.splitlines()

    # 提取字段
    # 2026-07-26 fix: fm.get("title") 偶尔返回 float/int（如数值被解析），用 str() 防御
    _raw_title = fm.get("title") or title or md_p.stem or "无标题"
    title = str(_raw_title).strip()
    _raw_author = fm.get("author") or author or "未知作者"
    author = str(_raw_author).strip()
    source_url = fm.get("source_url") or ""

    # 解析日期：优先 frontmatter 里的日期字段
    raw_date = (
        _to_date_str(fm.get("publish_time_raw") or "") or
        _to_date_str(fm.get("publish_time") or "") or
        _to_date_str(fm.get("publish_date") or "") or
        _to_date_str(fm.get("created") or "") or
        _to_date_str(fm.get("date") or "") or
        _to_date_str(md_p.stem[:10])  # 文件名开头 YYYYMMDD
    )
    if not raw_date:
        raw_date = _today_str()
    item_date = date.fromisoformat(raw_date[:10])
    date_str = raw_date[:10]  # YYYY-MM-DD

    # ID 去重（支持抖音/B站视频ID + 小红书 note_id）
    vid = _canonical_vid(source_url, md_p.stem)
    # 小红书 note_id 也作为 dedup key
    if not vid and platform == "xiaohongshu":
        vid = fm.get("note_id") or ""
    # 2026-08-15 fix #19: force_overwrite 供 OCR daemon 覆盖已 seen 的笔记.
    # 场景: Mac xhs 抓 → mark_seen, 然后 VM daemon OCR 完想覆盖写带 OCR 文字的版本,
    # 但 vid 已 seen 会被跳过 → vault 永远是空 OCR 版. 普通发布保持去重.
    if vid and _is_seen(platform, vid) and not force_overwrite:
        print(f"  ⏭️  [{platform}] {author}/{title[:30]}: 已缓存({vid[:16]}), 跳过")
        return None, None

    # 图片物化
    img_map = {}
    if images_dir:
        img_map = _materialize_images(platform, author, date_str,
                                      title, Path(images_dir))

    # 写博主子目录文件
    fpath = _write_author_file(platform, author, title, body_lines,
                               date_str, source_url, img_map)
    fname = fpath.name
    # 2026-08-15 fix: _mark_seen 移到 _write_author_file 成功后.
    # 原顺序 (mark_seen -> write) 会在写盘失败 / race 情况下把 note_id 写进 cache,
    # 下次跑批 _is_seen 命中跳过 -> 已写错或缺失的 vault md 永远不会被覆盖.
    # 0814 招财猫养基 / 阿基米 / 每日养基实录 / 百万快回本鸭 4 篇图链 ![](images/) 残留由此产生.
    if vid:
        _mark_seen(platform, vid)
    print(f"  ✅ [{platform}] {author}/{fname}")

    # 2026-08-04 修复: 不再生成 subscription/<plat>-hot.md 和 YYYYMM<plat>.md 索引,
    # 这些文件与 subscription/<plat>/<author>/<YYYY-MM-DD_title>.md 重复.
    # 2026-08-04 同时移除 subscription_log.md 台账写入 (改用跑批后自动 OP 报告).

    return str(fpath), {"platform": platform, "author": author, "title": title,
                        "date": date_str, "path": str(fpath)}


def _canonical_vid(url: str, stem: str) -> str:
    """从 URL 或 frontmatter note_id 提取视频/笔记 ID（支持抖音/B站/小红书/LinkedIn）"""
    if url:
        m = re.search(r'(video/|/)([0-9]{16,})', url)
        if m:
            return m.group(2)
        m = re.search(r'(BV[0-9A-Za-z]{10})', url)
        if m:
            return m.group(1)
        # xhs note_id 格式: 64位十六进制
        m = re.search(r'/([0-9a-f]{16,})', url, re.I)
        if m:
            return m.group(1)
        # LinkedIn job URL: /jobs/view/<job_id>
        m = re.search(r'/jobs/view/(\d{7,12})', url)
        if m:
            return f"li:{m.group(1)}"
    if len(stem) >= 16 and stem[:16].isdigit():
        return stem[:16]
    if re.match(r'BV[0-9A-Za-z]{10}', stem):
        return stem[:12]
    return ""


# ═══════════════════════════════════════════════════════════════
# 批量发布（搜索型平台：boss/jd/linkedin/tieba）
# ═══════════════════════════════════════════════════════════════

def push_aggregated_batch(platform: str, items: list,
                          today: date = None) -> dict:
    """
    批量发布搜索型平台条目到 subscription/<plat>/<YYYY-MM-DD_title>.md。
    搜索型平台不以博主为单位，直接写到平台根目录。
    2026-08-04 起不再生成 subscription/<plat>-hot.md / YYYYMM<plat>.md 索引。
    """
    today = today or date.today()
    # 2026-08-04: hot/monthly 索引文件已停用, 此处不再调用 _hot_path/_monthly_path
    plat_label = {"jd": "京东", "boss": "Boss直聘",
                  "linkedin": "领英", "tieba": "贴吧"}.get(platform, platform)

    results = []
    for item in items:
        try:
            title = item.get("title") or "无标题"
            author = item.get("author") or "未知作者"
            publish_date = item.get("publish_date") or _today_str()
            source_url = item.get("source_url") or ""
            body = item.get("body", "")

            # 防重
            vid = _canonical_vid(source_url, title)
            if vid and _is_seen(platform, vid):
                print(f"  ⏭️  [{platform}] {title[:40]}: 已存在, 跳过")
                continue
            if vid:
                _mark_seen(platform, vid)

            # 写文件到平台根目录（搜索型不用博主子目录）
            plat_dir = _plat_dir(platform)
            plat_dir.mkdir(parents=True, exist_ok=True)
            safe_title = _sanitize_filename(title)
            fname = f"{publish_date[:10]}_{safe_title}.md"
            fpath = plat_dir / fname
            n = 1
            while fpath.exists():
                fpath = plat_dir / f"{publish_date[:10]}_{safe_title}_{n}.md"
                n += 1

            import yaml
            content = "\n".join([
                "---",
                f"title: \"{title}\"",
                f"author: \"{author}\"",
                f"platform: \"{platform}\"",
                f"publish_date: \"{publish_date}\"",
                f"created: \"{datetime.now(TZ).isoformat()}\"",
                ("source_url: \"" + source_url + "\"" if source_url else ""),
                "---", "", body
            ])
            fpath.write_text(content, encoding="utf-8")

            # 2026-08-04: 不再更新 subscription/<plat>-hot.md (由子目录承担检索)

            results.append({"title": title, "path": str(fpath), "date": publish_date})
        except Exception as e:
            print(f"  ⚠️  [{platform}] {item.get('title','')}: {e}")

    # 2026-08-04: 不再生成 YYYYMM<plat>.md 月归档索引

    return {"hot": None, "monthly": {}, "count": len(results)}


# ═══════════════════════════════════════════════════════════════
# 旧版兼容（仅剪藏入口用到）
# ═══════════════════════════════════════════════════════════════

def push(md_path, images_dir, title, platform="link", author=None, parent=None) -> tuple:
    """剪藏单条 → vault/00_inbox/（含图片物化，2026-08-15 修复）。

    2026-08-15 修复: 旧版 push 完全忽略 images_dir, 而 process_url 的 finally 会
    shutil.rmtree(tmp) 把爬虫下载好的图片目录一起删掉 → 剪藏的微信/网页图片全部丢失,
    md 里残留 <img src="images/..."> 指向不存在的文件. 现补上:
      1) _materialize_images 把图复制到 vault/media/<plat>/<author>/
      2) 改写正文里 BOTH Markdown 图片 ![...](images/...) 和 HTML 图片 <img src="images/...">
         为 Obsidian wikilink ![[media/...]], 移动 md 也不断链.
    """
    from pathlib import Path as _P
    md_p = _P(md_path).resolve()
    vault_inbox = VAULT / "00_inbox"
    vault_inbox.mkdir(parents=True, exist_ok=True)
    text = md_p.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)
    title = title or fm.get("title") or md_p.stem
    author = author or fm.get("author") or ""

    # 图片物化 + 链接改写
    body_lines = body.splitlines()
    # 2026-08-15: 清理"只有空白字符(如 xhs-downloader 段间插入的孤立 tab)的行".
    # 这类行在 Obsidian 里会渲染成一条竖线且无任何语义, 统一替换为真正的空行(段落分隔),
    # 既消除竖线又保留段落间距. 注意只动"整行仅空白"的行, 不动有内容的行(避免破坏缩进/代码块).
    body_lines = ["" if ln.strip() == "" else ln for ln in body_lines]
    date_str = (_to_date_str(fm.get("publish_date") or fm.get("created") or "") or _today_str())[:10]
    img_map = {}
    if images_dir:
        img_map = _materialize_images(platform, author, date_str, title, _P(images_dir))
        if img_map:
            body_lines = _rewrite_image_links(body_lines, img_map)
            body_lines = _rewrite_html_img_tags(body_lines, img_map)
    # 重组: 保留原始 frontmatter + 改写后的正文
    if text.startswith("---\n"):
        _e = text.find("\n---\n", 4)
        _head = text[:_e + 6] if _e >= 0 else ""
    else:
        _head = ""
    new_body = "\n".join(body_lines).strip()
    new_text = (_head + "\n" + new_body + "\n") if _head else (new_body + "\n")

    dest = vault_inbox / f"{_now().strftime('%Y%m%d_%H%M%S')}_{_sanitize_filename(title)}.md"
    dest.write_text(new_text, encoding="utf-8")
    url = fm.get("source_url") or ""
    _nimg = len(img_map)
    print(f"  ✅ inbox: {dest.name}" + (f" (物化图片 {_nimg})" if _nimg else ""))
    return str(dest), {"title": title, "author": author, "url": url}


# ═══════════════════════════════════════════════════════════════
# 热身：确保目录存在
# ═══════════════════════════════════════════════════════════════

def _ensure_dirs():
    for plat in ["douyin", "bilibili", "xiaohongshu", "jd", "linkedin", "tieba"]:
        d = _plat_dir(plat)
        d.mkdir(parents=True, exist_ok=True)
    MEDIA.mkdir(parents=True, exist_ok=True)

_ensure_dirs()
