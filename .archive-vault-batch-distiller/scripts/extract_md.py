#!/usr/bin/env python3
"""Extract headings + intro summaries from all .md files under a directory."""
import os, re, glob, json, argparse


def norm_extract(path):
    txt = open(path, encoding="utf-8", errors="ignore").read()
    # strip frontmatter
    if txt.startswith("---"):
        m = re.match(r"^---\n.*?\n---\n", txt, re.S)
        if m:
            txt = txt[m.end():]
    lines = txt.splitlines()
    heads = [l for l in lines if re.match(r"^#{1,3} ", l)]
    body = [l for l in lines if l.strip() and not l.startswith("#")]
    intro = "\n".join(body[:20])
    return {
        "file": os.path.basename(path),
        "chars": len(txt),
        "lines": len(lines),
        "headings": heads[:14],
        "intro": intro[:900],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True, help="source directory containing .md files")
    parser.add_argument("--out", required=True, help="output json path")
    args = parser.parse_args()
    files = sorted(glob.glob(os.path.join(args.dir, "*.md")))
    data = [extract(f) for f in files]
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Extracted {len(data)} files -> {args.out}")


if __name__ == "__main__":
    main()
