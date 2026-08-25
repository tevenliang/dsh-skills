#!/usr/bin/env python3
"""从 03_daily/*.md 提取链接，批量抓取到 inbox"""

import sys as _sys
from pathlib import Path as _P
_SKILL_ROOT = str(_P(__file__).resolve().parent.parent)
if _SKILL_ROOT not in _sys.path:
    _sys.path.insert(0, _SKILL_ROOT)

import os, re, subprocess, sys, time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
FETCH_URL = SCRIPT_DIR / "fetch_url.sh"
from common.paths import daily_dir, inbox_dir
DAILY_DIR = daily_dir()

PLATFORMS = [
    'bilibili.com', 'b23.tv',
    'xiaohongshu.com', 'xhslink.com',
    'douyin.com', 'iesdouyin.com',
    'mp.weixin.qq.com',
]

def log(m):
    print(f"  {m}", flush=True)

def run(url):
    result = subprocess.run(
        ["bash", str(FETCH_URL), url, "--inbox"],
        capture_output=True, text=True, timeout=180
    )
    out = result.stdout + result.stderr
    print(out)
    return "BLOGGER_OK" in out

def main():
    seen = set()
    urls = []
    for f in sorted(DAILY_DIR.glob("*.md")):
        text = f.read_text(errors="ignore")
        for m in re.findall(r'https?://\S+', text):
            clean = re.sub(r'[)\],;<>\s].*$', '', m).strip()
            base = clean.split('?')[0]
            if not base or base in seen:
                continue
            if any(p in base for p in PLATFORMS):
                seen.add(base)
                urls.append(base)

    print(f"=== 发现 {len(urls)} 条链接 ===")
    if not urls:
        print("没有链接，退出")
        return

    success = fail = 0
    for url in urls:
        print(f"--- {url}")
        if run(url):
            success += 1
        else:
            fail += 1
        time.sleep(2)

    print(f"\n=== 完成: 成功 {success}，失败 {fail} ===")
    print("VM subscription-expert daemon 会在后台自动处理转录/总结")

if __name__ == "__main__":
    main()
