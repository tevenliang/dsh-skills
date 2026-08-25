#!/bin/bash
# xhs_ocr_rapid.sh — RapidOCR v9 (数据行学边界·跳过表头用语义列名)
#
# 新行为（v10）：生成新文档，不动原文件
#   输入: note.md
#   输出: note_ocr.md（原文结构保留，图片嵌入处替换为 OCR 转录）
#
# 用法:
#   bash xhs_ocr_rapid.sh <file.md>        # 生成 note_ocr.md
#   bash xhs_ocr_rapid.sh <file.md> dry-run  # 预览，不写文件
set -e

# ── 媒体目录检测(脱离 steven_vault) ────────────────────────────────
# 返回 cache_root/media; 迁移期同时返回 legacy steven_vault/media 作兜底
detect_media_dir() {
    SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
    MEDIA_DIR="$(python3 - "$SKILL_DIR" <<'PY' 2>/dev/null
import sys, os
sys.path.insert(0, os.path.join(sys.argv[1], 'scripts'))
import paths
print(paths.media_dir())
PY
)"
    LEGACY_MEDIA="$(python3 - "$SKILL_DIR" <<'PY' 2>/dev/null
import sys, os
sys.path.insert(0, os.path.join(sys.argv[1], 'scripts'))
import paths
print(paths.legacy_media_dir())
PY
)"
    if [ -z "$MEDIA_DIR" ]; then
        MEDIA_DIR="$HOME/WorkBuddy/MyWorkSpace/project_crawl/media"
    fi
    if [ -z "$LEGACY_MEDIA" ]; then
        LEGACY_MEDIA="$HOME/Documents/steven_vault/media"
    fi
}

[ -z "$1" ] && echo "用法: $0 <file.md> [dry-run]" && exit 1
FILE="$1"; DRY_RUN="${2:-}"; BASENAME=$(basename "$FILE")
[ ! -f "$FILE" ] && echo "❌ 文件不存在" && exit 1

# 输出文件: 原名_ocr.md（若输入已是 _ocr.md，则覆盖自身）
if [[ "$FILE" == *_ocr.md ]]; then
    OUT="$FILE"
else
    OUT="${FILE%.md}_ocr.md"
fi
echo "=== 处理: $BASENAME ==="
echo "    输出: $(basename "$OUT")"

detect_media_dir
TMP_PY=$(mktemp)
cat > "$TMP_PY" << 'PYEOF'
import sys, re, collections, os, datetime, subprocess, json

MEDIA_DIR   = sys.argv[1]
LEGACY_MEDIA= sys.argv[2]
FILE    = sys.argv[3]
OUT     = sys.argv[4]
DRY_RUN = len(sys.argv) > 5 and sys.argv[5] == "dry-run"

# ── 小工具 ──────────────────────────────────────────────────────────
def is_amount(s):   return bool(re.search(r'[万亿]', s))
def is_pct(s):     return '%' in s and bool(re.match(r'^[\+\-]?\d+\.\d+%$', s.strip()))
def is_noise(s):
    for kw in ["仅个人整理","不构成任何投资建议","今日核心看点","左滑查看",
                 "左滑","更多详情","横向对比","板块热度"]:
        if kw in s: return True
    return False
def clean(s): return re.sub(r'\s+', ' ', s).strip()

# ── 表格渲染 ───────────────────────────────────────────────────────
def make_table(rows):
    if not rows: return ""
    ncols   = max(len(r) for r in rows)
    col_w   = [max(len(r[j]) if j < len(r) else 0 for r in rows) for j in range(ncols)]
    lines   = []
    for i, row in enumerate(rows):
        cells = [row[j] if j < len(row) else "" for j in range(ncols)]
        lines.append("| " + " | ".join(c.ljust(col_w[j]) for j, c in enumerate(cells)) + " |")
        if i == 0:
            lines.append("|" + "|".join("-" * (col_w[j] + 2) for j in range(ncols)) + "|")
    return "\n".join(lines)

# ── OCR: 纯文本模式 ─────────────────────────────────────────────────
def text_output(result):
    groups = {}
    for item in result:
        box, text, score = item[0], item[1], item[2]
        y = round(box[0][1] / 18) * 18
        groups.setdefault(y, []).append((box[0][0], text))
    lines, prev_y = [], None
    for y in sorted(groups):
        row = sorted(groups[y], key=lambda x: x[0])
        line = " ".join(t for _, t in row if t.strip())
        if not line.strip() or is_noise(line): continue
        if prev_y and (y - prev_y) > 45: lines.append("")
        lines.append(line); prev_y = y
    return "\n".join(lines)

# ── OCR: Pipe 表格模式 ──────────────────────────────────────────────
def pipe_table(result):
    blocks = [b for b in result if '|' in b[1] and b[1].count('|') >= 2]
    if not blocks: return ""
    groups = collections.OrderedDict()
    for item in blocks:
        box, text = item[0], item[1]
        y = round(box[0][1] / 14) * 14
        groups.setdefault(y, []).append(text)
    rows = []
    for y in sorted(groups):
        parts = [p.strip() for p in " ".join(groups[y]).split('|') if p.strip()]
        if parts: rows.append(parts)
    return make_table(rows) if len(rows) > 1 else ""

# ── OCR: 自动表格模式 ───────────────────────────────────────────────
def auto_table(result):
    blocks_by_y = collections.OrderedDict()
    for item in result:
        box, text, score = item[0], item[1], item[2]
        if is_noise(text): continue
        y = round(box[0][1] / 14) * 14
        blocks_by_y.setdefault(y, []).append((box, text, score))
    if len(blocks_by_y) < 2: return ""
    total = sum(len(v) for v in blocks_by_y.values())
    if total < 5: return ""
    by_n = {}
    for y, row in blocks_by_y.items():
        n = len(row); by_n.setdefault(n, []).append((y, row))
    best_n = max(by_n.keys())
    if best_n < 3: return ""
    has_rank = False
    if 5 in by_n:
        for y, row in by_n[5]:
            sr = sorted(row, key=lambda x: x[0][0][0])
            if re.match(r'^\d+$', sr[0][1].strip()): has_rank = True; break
    _, ref_row = by_n[best_n][0]
    xs = [b[0][0][0] for b in ref_row]
    boundaries = [0] + [(xs[i]+xs[i+1])/2 for i in range(len(xs)-1)] + [1000]
    ncols = len(xs)
    headers = (["排名","基金名","板块","金额（元+份）","人数"]
               if has_rank else ["基金名","板块","金额（元+份）","人数"])
    hdr_kws = ["买入排名","卖出汇总","板块资金流向","总加仓","总撤退",
                "加仓明细","撤退明细","板块详情","今日加仓金额","今日撤退金额",
                "按买入金额","按卖出金额","今日关键信号","按买入金额从高到低",
                "今日加仓金额TOP20","排名鸡场名","今日最大信号"]
    def assign(blocks):
        cols = ["" for _ in range(ncols)]
        for box, text, score in blocks:
            xc = box[0][0]
            for j in range(ncols):
                if boundaries[j] <= xc < boundaries[j+1]:
                    cols[j] = (cols[j]+" "+text).strip() if cols[j] else text; break
        return [clean(c) for c in cols]
    out_rows, prev_y = [], None
    for y in sorted(blocks_by_y):
        row_blocks = blocks_by_y[y]
        all_txt = " ".join(b[1] for b in row_blocks)
        cols = assign(row_blocks)
        while cols and not cols[-1]: cols.pop()
        if not any(c for c in cols): continue
        is_hdr = any(kw in all_txt for kw in hdr_kws)
        if is_hdr and len(row_blocks) <= 4: continue
        if is_hdr:
            if len([c for c in cols[1:] if c.strip()]) < 2: continue
        first = sorted(row_blocks, key=lambda x: x[0][0][0])[0][1]
        if ("排名" in first or "鸡场" in first) and len([c for c in cols[1:] if c.strip()]) < 2: continue
        singletons = [c for c in cols if c.strip()]
        if len(singletons) == 1 and singletons[0] in ["持平","升温","降温","新进","偏多","偏空"]: continue
        if prev_y and (y - prev_y) < 20 and len(singletons) <= 2: continue
        cols = cols[:ncols]
        while len(cols) < ncols: cols.append("")
        out_rows.append(cols); prev_y = y
    table_rows = [r for r in out_rows if len([c for c in r if c.strip()]) >= max(2, ncols-1)]
    if has_rank:
        for r in table_rows:
            while len(r) < ncols: r.append("")
            if not r[0].strip(): r[0] = "-"
    if len(table_rows) >= 2:
        return make_table([headers] + table_rows)
    return ""

# ── 图片 OCR 入口 ────────────────────────────────────────────────────
def mmx_vision(img_path):
    """用 mmx vision describe 识别图片，失败返回 None"""
    try:
        r = subprocess.run(
            ["mmx", "vision", "describe",
             "--image", img_path,
             "--output", "json", "--quiet"],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            return None
        data = json.loads(r.stdout)
        if isinstance(data, dict):
            desc = data.get("content") or data.get("text") or ""
        else:
            desc = str(data)
        return desc.strip() or None
    except Exception:
        return None


def rapid_ocr_raw(img_path):
    """子进程跑 RapidOCR，避免单张图 segfault 拖垮整个文件。
    返回原始 result 列表；崩溃/超时返回 None；无文字返回 []"""
    code = (
        "import sys, json\n"
        "from rapidocr_onnxruntime import RapidOCR\n"
        "ocr = RapidOCR()\n"
        f"result, _ = ocr({img_path!r})\n"
        "if result:\n"
        "    print(json.dumps([[list(b[0]), b[1], b[2]] for b in result]))\n"
    )
    try:
        r = subprocess.run([sys.executable, "-c", code],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            sys.stderr.write(f"[rapid_ocr] 子进程异常(img={img_path}): {r.stderr[:200]}\n")
            return None
        if not r.stdout.strip():
            return []
        return json.loads(r.stdout)
    except subprocess.TimeoutExpired:
        sys.stderr.write(f"[rapid_ocr] 超时(img={img_path})\n")
        return None
    except Exception as e:
        sys.stderr.write(f"[rapid_ocr] 异常(img={img_path}): {e}\n")
        return None


def rapid_ocr(img_path):
    """本地 RapidOCR 识别（子进程隔离），失败返回空字符串"""
    result = rapid_ocr_raw(img_path)
    if not result:
        return ""
    for fn in (pipe_table, auto_table, text_output):
        out = fn(result)
        if out.strip(): return out
    return ""


def process_image(img_path):
    """
    OCR 模式由环境变量 XHS_OCR_MODE 控制:
      - local (默认): 只用 RapidOCR，不调 mmx
      - mmx:          优先 mmx vision，失败兜底 RapidOCR
      - mmx-only:      只用 mmx vision，不兜底
    """
    ocr_mode = os.environ.get("XHS_OCR_MODE", "local").strip().lower()

    if ocr_mode == "local":
        # 默认：纯本地
        return rapid_ocr(img_path)

    if ocr_mode in ("mmx", "mmx-only"):
        desc = mmx_vision(img_path)
        if desc:
            return desc
        if ocr_mode == "mmx-only":
            return ""
        # mmx 模式：兜底本地
        return rapid_ocr(img_path)

    # 未知模式，兜底本地
    return rapid_ocr(img_path)

# ── 主逻辑 ──────────────────────────────────────────────────────────
# 匹配 Markdown 标准图片语法: ![alt](media/xxx.jpg)
# 也兼容 Obsidian 嵌入语法: ![[media/xxx.jpg]]
# 兼容: ![alt](media/xxx.jpg) / ![alt](../../../media/xxx.jpg) / ![[media/xxx.jpg]]
# m.group(2) 始终是干净的 "media/xxx.jpg" (去掉所有 ../ 前缀)
IMG_PAT = re.compile(r'!?\[([^\]]*)\]\([^)]*?(media/[^)]+\.(?:jpg|png|gif|webp))\)')
FM_FIELD = re.compile(r'^([a-zA-Z_][a-zA-Z0-9_]*):\s*(.+?)\s*$', re.MULTILINE)

def parse_frontmatter(content):
    """提取 frontmatter 字段"""
    m = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not m: return {}
    out = {}
    for line in m.group(1).split('\n'):
        fm = FM_FIELD.match(line)
        if fm:
            v = fm.group(2).strip().strip('"').strip("'")
            out[fm.group(1)] = v
    return out

with open(FILE, encoding='utf-8') as f:
    content = f.read()

fm = parse_frontmatter(content)
img_count = 0
ocr_results = []   # [(img_rel, ocr_text), ...]

for line in content.split('\n'):
    m = IMG_PAT.search(line)
    if m:
        img_rel  = m.group(2)   # media/xxx.jpg
        fname = img_rel.split('media/')[-1]
        img_full = os.path.join(MEDIA_DIR, fname)
        if not os.path.exists(img_full) and os.path.isdir(LEGACY_MEDIA):
            img_full = os.path.join(LEGACY_MEDIA, fname)
        img_count += 1
        if not DRY_RUN and os.path.exists(img_full):
            result = process_image(img_full)
            ocr_results.append((img_rel, result))
        else:
            ocr_results.append((img_rel, ""))

if DRY_RUN:
    print(f"[dry-run] 发现 {img_count} 张图片，输出到 {os.path.basename(OUT)}")
else:
    # v13 新格式:只输出 OCR 文字,不含原图/正文
    out_lines = ["---"]
    for k in ["title", "publish_time", "author", "uid", "note_id", "source_url"]:
        v = fm.get(k, "")
        if v: out_lines.append(f'{k}: "{v}"')
    out_lines.append("category: xhs")
    out_lines.append('status: ["ocred"]')  # batch_processor 扫描到 ocred 跳过
    # source 字段动态设置
    _ocr_mode = os.environ.get("XHS_OCR_MODE", "local").strip().lower()
    if _ocr_mode == "local":
        _src = "rapidocr"
    elif _ocr_mode == "mmx":
        _src = "mmx_vision+rapidocr"
    elif _ocr_mode == "mmx-only":
        _src = "mmx_vision"
    else:
        _src = "rapidocr"
    out_lines.append(f"source: {_src}")
    out_lines.append(f'created: "{datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}"')
    out_lines.append("---")
    out_lines.append("")

    if img_count == 0:
        out_lines.append("(无图片)")
    else:
        out_lines.append("## OCR 转录")
        out_lines.append("")
        for i, (img_rel, ocr_text) in enumerate(ocr_results, 1):
            fname = img_rel.split('/')[-1]
            out_lines.append(f"### 图片 {i}: `{fname}`")
            out_lines.append("")
            if not DRY_RUN:
                if ocr_text.strip():
                    for ol in ocr_text.split('\n'):
                        out_lines.append(f"> {ol}")
                else:
                    out_lines.append("> (OCR 未识别到内容)")
            else:
                out_lines.append(f"> [dry-run] OCR: {img_rel}")
            out_lines.append("")

    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out_lines) + '\n')
    print(f"✅ 完成: {img_count} 张图片 → {os.path.basename(OUT)}")
PYEOF

python3 "$TMP_PY" "$MEDIA_DIR" "$LEGACY_MEDIA" "$FILE" "$OUT" "$DRY_RUN" || echo "⚠ OCR 进程异常退出(可能segfault)，跳过"
rm -f "$TMP_PY"
exit 0
