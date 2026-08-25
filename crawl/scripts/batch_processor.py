#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
subscription-crawl batch_processor — ing→ed 流水线 (v18, 合并后)
扫描 vault/subscription/，发现 ing 标签就处理，完成后替换为 ed
"""

import sys as _sys
from pathlib import Path as _P
_SKILL_ROOT = str(_P(__file__).resolve().parent.parent)
if _SKILL_ROOT not in _sys.path:
    _sys.path.insert(0, _SKILL_ROOT)

import datetime, json, os, re, subprocess, sys, yaml
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent.resolve()
COMMON    = SKILL_DIR / "common"
SCRIPTS   = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS))
from common.paths import notes_dir, logs_dir
LLM_SCR   = COMMON / "llm.py"
XHS_SCR   = SCRIPTS / "xhs_ocr_rapid.sh"

def load_config():
    try:
        with open(SKILL_DIR / "config.yaml") as f:
            return yaml.safe_load(f) or {}
    except: return {}

CONFIG    = load_config()
SUB       = str(notes_dir())
LOG       = str(logs_dir() / "batch_log.md")
PLATFORMS = CONFIG.get("summarization", {}).get("platforms", ["bilibili","douyin","xiaohongshu"])

print(f"[batch_processor v18] notes={SUB}", flush=True)

# ── frontmatter 读写 ────────────────────────────────────────────────
def get_status(fpath):
    try:
        with open(fpath, encoding="utf-8", errors="ignore") as fh:
            txt = fh.read()
        m = re.match(r'^---\s*\n(.*?)\n---\s*\n', txt, re.DOTALL)
        if not m: return []
        for line in m.group(1).splitlines():
            line = line.strip()
            if line.startswith('status:'):
                rest = line.split('status:',1)[1].strip()
                return yaml.safe_load(rest) if rest.startswith('[') else []
        return []
    except: return []

def replace_tags(fpath, replacements):
    """replacements: [(old, new), ...] 全文替换 frontmatter 中的标签"""
    try:
        with open(fpath, encoding="utf-8", errors="ignore") as fh:
            txt = fh.read()
        m = re.match(r'^(---\s*\n)(.*?)(\n---\s*\n)', txt, re.DOTALL)
        if not m: return False
        fm = m.group(2)
        for old, new in replacements:
            fm = fm.replace(old, new)
        new_txt = m.group(1) + fm + m.group(3) + txt[m.end():]
        with open(fpath, 'w', encoding='utf-8') as fh:
            fh.write(new_txt)
        return True
    except Exception as e:
        print(f"    ⚠️ replace_tags: {e}"); return False

# ── Action ─────────────────────────────────────────────────────────
def run_llm(fpath):
    r = subprocess.run([sys.executable, str(LLM_SCR), fpath],
                        capture_output=True, text=True, timeout=180)
    return r.returncode == 0

def run_ocr(fpath):
    r = subprocess.run(["bash", str(XHS_SCR), fpath],
                        capture_output=True, text=True, timeout=180)
    return r.returncode == 0

# ── 扫描 ────────────────────────────────────────────────────────────
def scan():
    results = []
    for plat in PLATFORMS:
        dp = os.path.join(SUB, plat)
        if not os.path.isdir(dp): continue
        for root, _, files in os.walk(dp):
            for fn in files:
                if not fn.endswith(".md"): continue
                if fn.startswith("batch_log") or fn.endswith("_ocr.md"): continue
                fp = os.path.join(root, fn)
                status = get_status(fp)
                ing = [t for t in status if t in
                       ("summarizing","abstracting","ocring")]
                if ing: results.append((fp, status, ing))
    return results

def append_log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"- {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")

def main():
    files = scan()
    if not files: print("✅ 无待处理文件"); return
    print(f"📋 共 {len(files)} 个文件待处理\n")

    total_ok = total_skip = total_err = 0
    for fp, status, ing_tags in files:
        rel = fp.split("/subscription/")[-1]
        print(f"▶ {rel}")
        print(f"  tags: {ing_tags}")

        done = []

        # ocring → ocred
        if "ocring" in ing_tags:
            print("  → ocring...", end=" ", flush=True)
            if run_ocr(fp):
                replace_tags(fp, [("ocring","ocred")])
                print("✅"); done.append("ocred")
            else:
                print("❌"); total_err += 1

        # summarizing → summarized + abstracting → abstracted（一次搞定）
        has_summarize = "summarizing" in ing_tags
        has_abstract  = "abstracting"  in ing_tags
        if has_summarize or has_abstract:
            label = "summarizing" + (" + abstracting" if has_abstract else "")
            print(f"  → {label}...", end=" ", flush=True)
            ok = run_llm(fp)
            replacements = []
            if has_summarize:  replacements.append(("summarizing",  "summarized"))
            if has_abstract:   replacements.append(("abstracting",  "abstracted"))
            if ok:
                replace_tags(fp, replacements)
                print("✅"); done.extend([r[1] for r in replacements])
            else:
                print("❌"); total_err += 1

        if done:
            total_ok += 1
            append_log(f"✅ {rel} → {done}")
        else:
            total_skip += 1

    print(f"\n{'='*50}\n完成: ✅{total_ok}  跳过: ⏭{total_skip}  错误: ❌{total_err}")

if __name__ == "__main__":
    main()
