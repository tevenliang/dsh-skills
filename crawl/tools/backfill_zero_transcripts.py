#!/usr/bin/env python3
"""backfill_zero_transcripts.py — 补转 0 字转录 md (0731 跑批留下的)

用法:
  python3 backfill_zero_transcripts.py --vault ~/Documents/steven_vault --max 5 --dry-run
  python3 backfill_zero_transcripts.py --vault ~/Documents/steven_vault --max 28
"""
import argparse, os, sys, re
from pathlib import Path

VAULT_DEFAULT = os.path.expanduser("~/Documents/steven_vault")

def find_zero_md(vault_root, platforms=("bilibili","douyin")):
    out = []
    for plat in platforms:
        d = os.path.join(vault_root, "subscription", plat)
        if not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for fn in files:
                if not fn.endswith(".md") or fn in (".DS_Store",) or fn.endswith("index.md"):
                    continue
                if re.match(r"^\d{6}(bilibili|douyin)\.md$", fn):
                    continue
                fp = os.path.join(root, fn)
                try:
                    txt = open(fp).read()
                except Exception:
                    continue
                if not txt.startswith("---"):
                    continue
                m = re.search(r'source_url:\s*\"?(https?://[^"\s]+)', txt)
                if not m:
                    continue
                parts = txt.split("---", 2)
                if len(parts) < 3:
                    continue
                body = parts[2].strip()
                main_body = re.sub(r"##\s*描述.*?(?=##|\Z)", "", body, flags=re.DOTALL).strip()
                if len(main_body) < 100:
                    out.append((fp, m.group(1), fn))
    return out

def backfill_one(md_path, source_url, crawl_root):
    sys.path.insert(0, os.path.join(crawl_root, "common-asr"))
    from transcribe import transcribe
    import tempfile
    tmp = tempfile.mkdtemp(prefix="backfill_")
    text, src = transcribe(source_url, tmp_dir=tmp, keep_wav_on_fail=False)
    with open(md_path) as f:
        txt = f.read()
    new_section = f"\n## 转录\n\n{text.strip()}\n"
    if "## 转录" in txt:
        txt = re.sub(r"##\s*转录.*?(?=##|\Z)", new_section, txt, flags=re.DOTALL)
    else:
        parts = txt.split("---", 2)
        if len(parts) >= 3:
            txt = parts[0] + "---" + parts[1] + "---" + parts[2] + new_section
        else:
            txt = txt + new_section
    with open(md_path, "w") as f:
        f.write(txt)
    return len(text), src

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--vault", default=VAULT_DEFAULT)
    p.add_argument("--max", type=int, default=28)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--crawl-root", default=os.path.expanduser("~/.agents/skills/crawl"))
    a = p.parse_args()
    targets = find_zero_md(a.vault)
    print(f"=== 找到 {len(targets)} 个 0 字 md ===\n")
    if a.dry_run:
        for fp, url, fn in targets[:a.max]:
            print(f"  {fn}")
            print(f"    URL: {url}")
        print(f"\n--max {a.max}: 本次会补 {min(len(targets), a.max)} 条")
        return
    n_ok = n_fail = 0
    for i, (fp, url, fn) in enumerate(targets[:a.max], 1):
        print(f"\n[{i}/{min(len(targets), a.max)}]")
        try:
            nchars, src = backfill_one(fp, url, a.crawl_root)
            print(f"  ✅ {fn} -> {nchars} chars (src={src})")
            n_ok += 1
        except Exception as e:
            print(f"  ⚠️ {fn}: {str(e)[:200]}")
            n_fail += 1
    print(f"\n=== 完成: 成功 {n_ok} / 失败 {n_fail} ===")

if __name__ == "__main__":
    main()
