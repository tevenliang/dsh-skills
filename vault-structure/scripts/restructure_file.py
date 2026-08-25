#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""restructure_file.py — vault-structure 的脚本化结构重组（对齐 vault-summary）。

读 md → parse_blocks 判定是否需要重组（正文标题 < MIN_HEADINGS）→ glm-4-flash 识别
伪标题 / 缺失标题 → 返回操作清单 → 安全套用到文件 → parse_blocks 复验。

只改标题行，绝不改动正文、图片、链接、分隔线，也不动 `## 总结`。

用法:
    restructure_file.py <md_file> [--engine glm] [--dry-run]
    restructure_file.py --help
"""
import sys, os, re, json, argparse, subprocess
from pathlib import Path

# ── 路径 ───────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
CRED = Path.home() / ".agents" / "credentials" / "ominicrawl" / "zhipu.json"

# ── 引擎：glm-4-flash（zhipu 免费档）────────────────────
GLM_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
GLM_MODEL = "glm-4-flash"

# ── 阈值 ───────────────────────────────────────────────
# 正文标题（排除 ## 总结）< MIN_HEADINGS → 需要重组。
# 设为 2：仅 H1 标题、无章节结构的文件（inbox 主力）会被结构化为 ≥2 标题。
# 安全性由 validate() 的「标题质量闸门」兜底（含句末标点/过长/层级跳跃一律拒绝），
# 因此即便 GLM 想过度转换也会被拦截、文件保持不动，不会损坏正文。
MIN_HEADINGS = 2
MIN_CHARS = 300           # 正文太短不处理

SYSTEM_PROMPT = """你是 Markdown 结构重组专家。给定一个 Obsidian vault 文档（通常是公众号 / 网页转存稿），
只分析其标题层级结构，返回 JSON 操作清单。

核心原则：标题是后续内容的【标签】，不是内容本身。
- 只有当某行明显是【章节小标题】时才转换为标题：短文本（建议 ≤ 30 字）、无句末标点（。！？；：）、
  常带 ①/②/数字/emoji/• 等标记，或明显是短语而非完整句子。
- 绝不要把包含完整句意、带句末标点、或超过 30 字的正文段落转成标题。
- 若全文是流水 prose、没有明显章节标题，则【不要转换任何段落】，
  只在开头引言前插入 ## 前言、结尾前插入 ## 写在最后（如果原本没有对应标题）。

识别与修复：
1. 伪装段落：纯数字开头(01/02)、无句末标点、短文本(<30字)的章节标题行 → 转 ##
2. 缺失标题：开头引言段或结尾结语段连续正文 > 3 段且无标题 → 插 ## 前言 / ## 写在最后
3. 层级跳跃：首行是链接而非 # 标题 → 首行链接升为 # H1

严格约束：
- 只返回操作清单，绝不修改正文、图片、链接、分隔线、代码块
- 不要动含 '## 总结' 的行
- 保持 # H1 为首个标题；若文档无 H1，把首行标题升为 #
- 不出现层级跳跃（有 ### 前必先有 ##）
- old / anchor 必须是文件真实存在的整行原文（精确匹配）
- 输出纯 JSON，不用 markdown 代码块包裹

格式：
{
  "operations": [
    {"op": "convert", "old": "旧行原文", "new_level": 2},
    {"op": "insert_before", "anchor": "锚点行开头", "heading": "## 标题"}
  ]
}
无需改动则返回 {"operations": []}

错误示例（禁止）：把"Codex 和 ChatGPT 合体之后，在 GPT 5.6 的加持下活跃用户突破 1000 万"这种完整句子转成标题。
"""


# ── 工具 ───────────────────────────────────────────────
def strip_frontmatter(md: str) -> str:
    if md.startswith("---"):
        end = md.find("\n---", 3)
        if end != -1:
            return md[end + 4:]
    return md


def content_heading_count(md: str) -> int:
    """统计正文标题数（排除 ## 总结）。"""
    n = 0
    for ln in md.splitlines():
        if re.match(r"^#{1,6}\s", ln) and not ln.strip().startswith("## 总结"):
            n += 1
    return n


def get_key() -> str:
    try:
        return json.loads(CRED.read_text(encoding="utf-8")).get("api_key", "")
    except Exception:
        return os.environ.get("ZHIPU_API_KEY", "")


def call_glm(system: str, user_content: str, api_key: str) -> str:
    import requests
    resp = requests.post(
        GLM_ENDPOINT,
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        json={
            "model": GLM_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
            "max_tokens": 2000,
        },
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def parse_json_strict(text: str) -> dict:
    """从模型输出里提取第一个 {...} JSON 块。"""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError("找不到 JSON 块")
    return json.loads(text[start:end + 1])


def _norm(line: str) -> str:
    """归一化一行用于容错匹配：去换行、左侧空白、blockquote(>)、标题井号(#)。"""
    s = line.rstrip("\n")
    s = s.lstrip()
    while s.startswith(">") or s.startswith("#"):
        s = s[1:]
    return s.strip()


def apply_operations(lines, ops):
    """把操作清单套用到行列表上，返回 (新行列表, 是否有实质改动)。

    设计原则：单条 op 匹配失败 → 跳过并告警（不整体抛错），保证一次成功的 op
    不会被另一条幻觉 op 拖垮；只有「全部 op 都没匹配」时才抛错，避免把 GLM 的
    垃圾输出当成成功处理。真正的防 corruption 兜底在 validate()。
    """
    any_matched = False
    changed = False
    skipped = []
    for op in ops:
        kind = op.get("op")
        if kind == "convert":
            target = op["old"].rstrip()
            level = int(op.get("new_level", 2))
            tnorm = _norm(target)
            matched = False
            for i, ln in enumerate(lines):
                if _norm(ln) == tnorm:
                    core = ln.rstrip("\n").rstrip()
                    if core.lstrip().startswith("#"):
                        matched = True  # 已是标题，跳过（无操作）
                    else:
                        lines[i] = "#" * level + " " + core + "\n"
                        matched = True
                        changed = True
                    break
            if matched:
                any_matched = True
            else:
                skipped.append(f"convert 未匹配(跳过): {target!r}")
        elif kind == "insert_before":
            anchor = op["anchor"]
            heading = op["heading"].rstrip()
            if not heading.startswith("#"):
                heading = "## " + heading
            anorm = _norm(anchor)
            matched = False
            for i, ln in enumerate(lines):
                ln_norm = _norm(ln)
                if ln_norm.startswith(anorm) or anorm in ln_norm:
                    lines.insert(i, heading + "\n")
                    matched = True
                    changed = True
                    break
            if matched:
                any_matched = True
            else:
                skipped.append(f"insert_before 未匹配 anchor(跳过): {anchor!r}")
        else:
            skipped.append(f"未知 op(跳过): {kind!r}")
    for s in skipped:
        print(f"[warn] {s}", file=sys.stderr)
    if ops and not any_matched:
        raise RuntimeError(f"全部 {len(ops)} 条 op 均未能匹配，疑似 GLM 输出与原文不符")
    return lines, changed


def validate(md_text: str):
    """复验结构合法性，返回 (ok, reason)。"""
    lines = md_text.splitlines()
    h1 = [l for l in lines if re.match(r"^#\s", l)]
    if len(h1) != 1:
        return False, f"H1 数量 = {len(h1)}（应为 1）"
    levels = [len(re.match(r"^(#+)", l).group(1)) for l in lines if re.match(r"^#{1,6}\s", l)]
    prev = 0
    for lv in levels:
        if lv - prev > 1:
            return False, f"层级跳跃 {prev} -> {lv}"
        prev = lv
    # 标题质量：H2+ 不得含句末标点、不得过长（防止把正文段落误当标题）
    for ln in lines:
        m = re.match(r"^(#{1,6})\s", ln)
        if not m:
            continue
        level = len(m.group(1))
        title = ln[m.end():].strip()
        if level >= 2 and re.search(r"[。；：]", title):
            return False, f"标题含句末标点(疑似正文当标题): {title[:24]}"
        if level >= 2 and len(title) > 50:
            return False, f"标题过长({len(title)}字): {title[:24]}"
    content = [l for l in lines if re.match(r"^#{1,6}\s", l) and not l.strip().startswith("## 总结")]
    if len(content) < MIN_HEADINGS:
        return False, f"正文标题仅 {len(content)} < {MIN_HEADINGS}（未产生有效结构）"
    return True, ""


# ── 主流程 ─────────────────────────────────────────────
def restructure(md_path: Path, engine: str = "glm", dry_run: bool = False) -> str:
    md = md_path.read_text(encoding="utf-8")
    body = strip_frontmatter(md)
    if len(body) < MIN_CHARS:
        print(f"[skip] {md_path.name}: 正文 {len(body)} 字符 < {MIN_CHARS}")
        return "skip"

    n = content_heading_count(md)
    if n >= MIN_HEADINGS:
        print(f"[skip] {md_path.name}: 已有 {n} 个正文标题，无需重组")
        return "skip"

    api_key = get_key()
    if not api_key:
        raise RuntimeError("找不到 zhipu api_key（~/.agents/credentials/ominicrawl/zhipu.json 或 ZHIPU_API_KEY）")

    ops = None
    last_err = None
    for attempt in range(2):
        try:
            raw = call_glm(SYSTEM_PROMPT, md, api_key)
            ops = parse_json_strict(raw).get("operations", [])
            break
        except Exception as e:
            last_err = e
            print(f"[retry {attempt+1}/2] glm/json 失败: {e}", file=sys.stderr)
    if ops is None:
        raise RuntimeError(f"glm 调用/解析连续失败: {last_err}")
    if not ops:
        print(f"[skip] {md_path.name}: LLM 判定无需改动")
        return "skip"

    lines = md.splitlines(keepends=True)
    new_lines, changed = apply_operations(lines, ops)
    if not changed:
        # 所有 op 都是 no-op（例如 GLM 对已有标题发 convert）→ 视为无需改动
        print(f"[skip] {md_path.name}: LLM 操作均为无实质改动")
        return "skip"
    new_md = "".join(new_lines)

    ok, reason = validate(new_md)
    if not ok:
        raise RuntimeError(f"复验失败: {reason}（不改写文件）")

    if dry_run:
        print(f"[dry] {md_path.name}: {len(ops)} 项操作（不写回）")
        print(new_md)
        return "dry"

    md_path.write_text(new_md, encoding="utf-8")
    print(f"[done] {md_path.name}: {len(ops)} 项操作")
    return "done"


def main():
    ap = argparse.ArgumentParser(description="vault-structure 脚本化结构重组")
    ap.add_argument("md_path")
    ap.add_argument("--engine", default="glm", help="固定 glm（zhipu 免费档）")
    ap.add_argument("--dry-run", action="store_true", help="只打印结果不写回")
    args = ap.parse_args()

    p = Path(args.md_path)
    if not p.exists():
        sys.stderr.write(f"❌ 文件不存在: {p}\n")
        sys.exit(1)

    try:
        status = restructure(p, engine=args.engine, dry_run=args.dry_run)
    except Exception as e:
        sys.stderr.write(f"❌ {p.name}: {e}\n")
        sys.exit(1)

    if status == "skip":
        sys.exit(0)
    sys.exit(0)


if __name__ == "__main__":
    main()
