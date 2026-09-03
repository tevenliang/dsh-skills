#!/usr/bin/env python3
"""extract_md.py — vault-wiki v8 Step 1：抽取目录下所有 md 的 frontmatter + 标题树 + 开头摘要。

用途：给 LLM 提供上下文摘要，避免一次性读完整个目录爆上下文。
同时识别 `_2`/副本/emoji 前缀的重复变体，供 Step 0 dedupe 参考。

用法：
    python3 extract_md.py --dir /path/to/L2 --out /tmp/L2_extract.json
    python3 extract_md.py --dir /path/to/L2                # 输出到 stdout
    python3 extract_md.py --dir /path/to/L2 --include-frontmatter  # 包含 frontmatter (默认包含)

输出 JSON：
    {
      "dir": "/path/to/L2",
      "file_count": N,
      "total_bytes": N,
      "files": [
        {
          "path": "相对 dir 的相对路径",
          "abs_path": "绝对路径",
          "size": 1234,
          "frontmatter": { ... } | null,
          "h1": ["# Title 1", ...],
          "h2": ["## Section 1", ...],
          "snippet": "前 N 字符的正文预览(去 frontmatter)"
        }, ...
      ]
    }
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path


# 标题匹配（# 后空格起算，行首 # 开头才算）
H_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(text):
    """从 md 文本顶部抽取 frontmatter。极简 YAML：仅支持 key: value 与 key: [list]。
    不引入 pyyaml 依赖（agent 上下文已用 yaml 但脚本保持最轻）。
    """
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None
    block = m.group(1)
    fm = {}
    current_list_key = None
    for raw in block.splitlines():
        if not raw.strip():
            continue
        # list item
        if raw.lstrip().startswith("- ") and current_list_key:
            val = raw.lstrip()[2:].strip().strip('"').strip("'")
            fm.setdefault(current_list_key, []).append(val)
            continue
        # key: value
        if ":" in raw:
            k, _, v = raw.partition(":")
            k = k.strip()
            v = v.strip()
            if v == "":
                current_list_key = k
                fm[k] = []
            elif v == "[]":
                fm[k] = []
                current_list_key = None
            elif v.startswith("[") and v.endswith("]"):
                inner = v[1:-1].strip()
                items = [x.strip().strip('"').strip("'") for x in inner.split(",") if x.strip()]
                fm[k] = items
                current_list_key = None
            else:
                fm[k] = v.strip('"').strip("'")
                current_list_key = None
            continue
    return fm


def extract_titles(text, levels=(1, 2, 3)):
    """抽 H1-H6 标题列表，按出现顺序。levels 控制返回哪几级。"""
    out = []
    for m in H_RE.finditer(text):
        hashes, content = m.group(1), m.group(2)
        level = len(hashes)
        if level in levels:
            prefix = "#" * level
            out.append(f"{prefix} {content}")
    return out


def extract_snippet(text, max_chars=600):
    """开头摘要：剥 frontmatter 后取前 max_chars 字（按行截断，不破字）。"""
    body = FRONTMATTER_RE.sub("", text, count=1).lstrip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    if len(body) <= max_chars:
        return body
    cut = body[:max_chars]
    # 截到最后一个换行
    if "\n" in cut:
        cut = cut.rsplit("\n", 1)[0]
    return cut + "\n…"


def safe_rel(p, base):
    try:
        return str(p.relative_to(base))
    except ValueError:
        return p.name


def extract_dir(dir_path, include_frontmatter=True, snippet_chars=600):
    dir_path = Path(dir_path).resolve()
    if not dir_path.is_dir():
        raise SystemExit(f"ERROR: not a directory: {dir_path}")

    files = []
    total_bytes = 0
    for p in sorted(dir_path.rglob("*.md")):
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            files.append({
                "path": safe_rel(p, dir_path),
                "abs_path": str(p),
                "size": 0,
                "frontmatter": None,
                "h1": [],
                "h2": [],
                "snippet": f"[read error: {e}]",
            })
            continue
        size = len(text.encode("utf-8"))
        total_bytes += size
        fm = parse_frontmatter(text) if include_frontmatter else None
        titles = extract_titles(text, levels=(1, 2))
        h1 = [t for t in titles if t.startswith("# ")]
        h2 = [t for t in titles if t.startswith("## ")]
        files.append({
            "path": safe_rel(p, dir_path),
            "abs_path": str(p),
            "size": size,
            "frontmatter": fm,
            "h1": h1,
            "h2": h2,
            "snippet": extract_snippet(text, snippet_chars),
        })

    return {
        "dir": str(dir_path),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "files": files,
    }


def main():
    ap = argparse.ArgumentParser(description="Extract md files: frontmatter + titles + snippet")
    ap.add_argument("--dir", required=True, help="directory of .md files")
    ap.add_argument("--out", help="output JSON path (default: stdout)")
    ap.add_argument("--include-frontmatter", action="store_true", default=True,
                    help="include frontmatter in output (default: true)")
    ap.add_argument("--no-frontmatter", dest="include_frontmatter", action="store_false")
    ap.add_argument("--snippet-chars", type=int, default=600,
                    help="max chars per snippet (default 600)")
    args = ap.parse_args()

    result = extract_dir(
        args.dir,
        include_frontmatter=args.include_frontmatter,
        snippet_chars=args.snippet_chars,
    )

    out = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"OK: wrote {args.out} ({len(result['files'])} files, {result['total_bytes']} bytes)")
    else:
        print(out)


if __name__ == "__main__":
    main()
