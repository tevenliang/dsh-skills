#!/usr/bin/env python3
"""backfill_0801.py — 补 0801 跑批漏掉的空正文 md (cooldown-skip bug).

复用 backfill_v2 的 B 站全链路 (bvid -> cid -> playurl -> m4s -> wav -> transcribe).
复用 backfill_zero_transcripts 的找文件 + 筛选逻辑, 限定 0801.

修复背景 (issue #16, 2026-08-01):
  cooldown 期间 14 条视频被 ASR.FATAL 跳过 → 写 "0 字转录" → 
  cooldown 结束后 supervisor 继续处理队列新视频, 不回补被跳过的 7 条 (实际数 6-9 条).

用法:
  python3 backfill_0801.py --dry-run            # 列出 0801 待补
  python3 backfill_0801.py --max 10             # 补前 10 条 (0801 共 6-9 条)
"""
import argparse, os, sys, re
from pathlib import Path

CRAWL_ROOT = os.path.expanduser("~/.agents/skills/crawl")
VAULT_DEFAULT = os.path.expanduser("~/Documents/steven_vault")

# 路径配置 (复用 backfill_v2 的全链路)
sys.path.insert(0, CRAWL_ROOT)
sys.path.insert(0, os.path.join(CRAWL_ROOT, "ingest-bilibili", "bilibili"))
sys.path.insert(0, os.path.join(CRAWL_ROOT, "ingest-douyin", "douyin_api"))
sys.path.insert(0, os.path.join(CRAWL_ROOT, "common-asr"))


def find_0801_targets(vault_root):
    """找 0801 空正文 md (filename 以 2026-08-01_ 开头 或 frontmatter created: 2026-08-01) 且正文 < 100 字."""
    targets = []
    for plat in ("bilibili", "douyin"):
        plat_dir = os.path.join(vault_root, "subscription", plat)
        if not os.path.isdir(plat_dir):
            continue
        for root, _, files in os.walk(plat_dir):
            for fn in files:
                if not fn.endswith(".md") or fn == ".DS_Store" or fn.endswith("index.md"):
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
                m = re.search(r'source_url:\s*"?(https?://[^"\s]+)', txt)
                if not m:
                    continue
                # 限定 0801 (filename 或 frontmatter)
                is_0801 = fn.startswith("2026-08-01_") or ("created: 2026-08-01" in txt[:500])
                if not is_0801:
                    continue
                # 正文长度 < 100 (复用 find_zero_md 逻辑, 排除 ## 描述)
                parts = txt.split("---", 2)
                if len(parts) < 3:
                    continue
                body = parts[2].strip()
                main_body = re.sub(r"##\s*描述.*?(?=##|\Z)", "", body, flags=re.DOTALL).strip()
                if len(main_body) < 100:
                    targets.append((fp, m.group(1), fn, plat))
    return targets


def backfill_bili(md_path, source_url, fn):
    """复用 backfill_v2.backfill_one_async 写回原位 (不移动到 _to_backfill)."""
    from backfill_v2 import backfill_one_async
    import asyncio
    # backfill_v2 期望 md 在 _to_backfill_0731, 但我们要写回原位, 所以 hack 一下:
    # 直接调它的内部 backfill_one_async, 然后确保它写回原 md_path (不是 moves)
    # backfill_v2 内部: target = vault_root/subscription/rel (从 _to_backfill_0731 算出)
    # 我们这里直接 inline 调用但只取 transcript, 不用它的 move 逻辑
    from bili_feed import _load_bili_cookie, audio_to_wav
    from crawlers.bilibili.web.web_crawler import BilibiliWebCrawler
    from transcribe import transcribe

    bvid = source_url.rstrip('/').split('/')[-1]
    if not bvid.startswith('BV'):
        return None, f"not bvid: {source_url}"
    cookie = _load_bili_cookie()
    if not cookie:
        return None, "no bili cookie"

    async def _go():
        crawler = BilibiliWebCrawler()
        info = await crawler.fetch_one_video(bvid)
        cid = info.get('data', {}).get('cid', 0)
        if not cid:
            return None, "no cid"
        pu = await crawler.fetch_video_playurl(bv_id=bvid, cid=str(cid), qn='64')
        audio_url = ''
        audios = pu.get('data', {}).get('dash', {}).get('audio', [])
        if audios:
            audio_url = audios[0].get('baseUrl') or audios[0].get('base_url', '')
        if not audio_url:
            durls = pu.get('data', {}).get('durl', [])
            if durls:
                audio_url = durls[0].get('url', '')
        if not audio_url:
            return None, "no audio_url"
        hdrs = (
            'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36\r\n'
            f'Referer: https://www.bilibili.com/video/{bvid}/\r\n'
            f'Cookie: {cookie}\r\n'
        )
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix=f"bf0801_{bvid}_")
        wav_path = os.path.join(tmpdir, 'v.wav')
        if not audio_to_wav(audio_url, wav_path, headers=hdrs):
            return None, "audio_to_wav fail"
        try:
            text, src = transcribe(wav_path)
        except RuntimeError as e:
            return None, f"ASR.FATAL: {str(e)[:120]}"
        return (text, src), None

    return asyncio.run(_go())


def write_transcript_to_md(md_path, text, source):
    """把转录文本注入到 md 文件 (复用 backfill_zero_transcripts 的格式)."""
    with open(md_path) as f:
        txt = f.read()
    # 优先用 apply_transcript 的格式 (transcribe.py 已提供)
    from transcribe import apply_transcript
    apply_transcript(md_path, text, source=source)
    return len(text)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--vault", default=VAULT_DEFAULT)
    p.add_argument("--max", type=int, default=999)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    targets = find_0801_targets(a.vault)
    print(f"=== 0801 空正文 md: {len(targets)} 条 ===\n")
    for fp, url, fn, plat in targets:
        print(f"  [{plat}] {fn}")
        print(f"    URL: {url}")
        print(f"    MD: {fp}")
    print()

    if a.dry_run:
        print(f"--max {a.max}: 本次会补 {min(len(targets), a.max)} 条")
        return

    n_ok = n_fail = 0
    _consec_fail = 0
    for i, (fp, url, fn, plat) in enumerate(targets[:a.max], 1):
        print(f"\n[{i}/{min(len(targets), a.max)}] [{plat}] {fn}")
        print(f"  URL: {url}")
        try:
            if plat == "bilibili":
                res, err = backfill_bili(fp, url, fn)
            else:
                # Douyin: 直接 URL 走 transcribe (新极简版支持 URL stream)
                from transcribe import transcribe
                import tempfile
                tmp = tempfile.mkdtemp(prefix="bf0801_dy_")
                res, err = None, None
                try:
                    text, src = transcribe(url, tmp_dir=tmp)
                    res = (text, src)
                except RuntimeError as e:
                    err = f"ASR.FATAL: {str(e)[:120]}"
            if err:
                print(f"  ⚠️ {err}")
                n_fail += 1
                _consec_fail += 1
                if _consec_fail >= 3:
                    print(f"\n❌ 连续 3 失败, 退出避免空跑")
                    break
                print(f"  [backoff] 失败后等 60s...")
                import time; time.sleep(60)
                continue
            text, src = res
            nchars = write_transcript_to_md(fp, text, src)
            print(f"  ✅ -> {nchars} chars (src={src})")
            n_ok += 1
            _consec_fail = 0
        except Exception as e:
            print(f"  ⚠️ 顶层错误: {str(e)[:200]}")
            n_fail += 1
            _consec_fail += 1

    print(f"\n=== 完成: 成功 {n_ok} / 失败 {n_fail} ===")


if __name__ == "__main__":
    main()
