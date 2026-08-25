#!/usr/bin/env python3
"""
backfill_v2.py — per-bvid 回灌 0 字 md (用 crawl ingest 工具链)

2026-07-31 v2:
- 不用 transcribe(URL) (B站 ffmpeg 直接 stream 失败)
- 改用: bvid -> view API 拿 cid -> playurl API 拿 audio_url
       -> urllib + cookie 下载 m4s -> ffmpeg wav -> transcribe(wav)
- 完全复用 crawl 项目的 cookie / audio_to_wav / transcribe
- 单条顺序处理 (PARALLEL=1, 用户决策低 Mac 资源)

用法:
  python3 backfill_v2.py --dry-run --max 3   # 看列表
  python3 backfill_v2.py --max 5              # POC 5 条
  python3 backfill_v2.py                      # 全跑
"""
import argparse, os, sys, asyncio, tempfile, json, re
from pathlib import Path

# ingest-bilibili 的工具链
sys.path.insert(0, "/Users/tianwenliang/.agents/skills/crawl")
sys.path.insert(0, "/Users/tianwenliang/.agents/skills/crawl/ingest-bilibili/bilibili")
sys.path.insert(0, "/Users/tianwenliang/.agents/skills/crawl/ingest-douyin/douyin_api")
sys.path.insert(0, '/Users/tianwenliang/.agents/skills/crawl/common-asr')

from bili_feed import (
    _load_bili_cookie, audio_to_wav, log, yml_escape
)
from crawlers.bilibili.web.web_crawler import BilibiliWebCrawler
from transcribe import transcribe


async def backfill_one_async(md_path, source_url, vault_root):
    """对单条 md 重跑转录.
    流程: bvid -> view API (cid) -> playurl API (audio_url)
         -> cookie 下载 m4s -> ffmpeg 转 wav -> transcribe(wav)
    """
    bvid = source_url.rstrip('/').split('/')[-1]
    if not bvid.startswith('BV'):
        print(f"    ⚠️ 不是 B 站 bvid, 跳过: {source_url}")
        return False
    
    cookie = _load_bili_cookie()
    if not cookie:
        print(f"    ⚠️ B 站 cookie 未配置 (~/.agents/credentials/ominicrawl/bilibili.txt)")
        return False
    
    # 用 crawl 的 crawler (现在它的 init 已经是 ok 的)
    crawler = BilibiliWebCrawler()  # 从 config.yaml 读 cookie
    
    # 1. bvid -> info
    try:
        info = await crawler.fetch_one_video(bvid)
        d = info.get('data', {})
        cid = d.get('cid', 0)
        title = d.get('title', '')
        if not cid:
            print(f"    ⚠️ 拿不到 cid (视频不存在/已删除?): {bvid}")
            return False
    except Exception as e:
        print(f"    ⚠️ fetch_one_video 失败: {str(e)[:100]}")
        return False
    
    # 2. cid -> audio_url (兼容 dash.audio + durl 两种格式)
    try:
        pu = await crawler.fetch_video_playurl(bv_id=bvid, cid=str(cid), qn='64')
        data_pu = pu.get('data', {})
        audio_url = ''
        audios = data_pu.get('dash', {}).get('audio', [])
        if audios:
            audio_url = audios[0].get('baseUrl') or audios[0].get('base_url', '')
        if not audio_url:
            durls = data_pu.get('durl', [])
            if durls:
                audio_url = durls[0].get('url', '')
        if not audio_url:
            print(f"    ⚠️ audio_url 没拿到 (dash+durl 都空): {bvid}")
            return False
    except Exception as e:
        print(f"    ⚠️ fetch_video_playurl 失败: {str(e)[:100]}")
        return False
    
    # 3. audio_url + cookie -> wav
    hdrs = (
        'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36\r\n'
        f'Referer: https://www.bilibili.com/video/{bvid}/\r\n'
        f'Cookie: {cookie}\r\n'
    )
    
    tmpdir = tempfile.mkdtemp(prefix=f"bf_{bvid}_")
    wav_path = os.path.join(tmpdir, 'v.wav')
    if not audio_to_wav(audio_url, wav_path, headers=hdrs):
        print(f"    ⚠️ audio_to_wav 下载失败: {bvid}")
        return False
    wav_size = os.path.getsize(wav_path) / 1024 / 1024
    print(f"    wav: {wav_size:.1f}MB")
    
    # 4. transcribe(wav) — 走新 retry 代码
    try:
        text, src = transcribe(wav_path)
        print(f"    transcribe: {len(text)} chars (src={src})")
    except RuntimeError as e:
        print(f"    ⚠️ ASR.FATAL: {str(e)[:150]}")
        return False
    except Exception as e:
        print(f"    ⚠️ transcribe 其它错误: {str(e)[:150]}")
        return False
    
    # 5. 回写到原 vault md 位置 (在 vault_root subscription/<plat>/<author>/<title>.md)
    # 计算原订阅路径: _to_backfill_0731/<rel> -> vault_root/subscription/<rel>
    rel = os.path.relpath(md_path, '/Users/tianwenliang/Documents/steven_vault/_to_backfill_0731')
    target = os.path.join(vault_root, 'subscription', rel)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    
    try:
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
        # 写回原 vault 位置 (而不是 _to_backfill)
        with open(target, 'w') as f:
            f.write(txt)
        # 删除 _to_backfill 副本
        try:
            os.remove(md_path)
        except Exception:
            pass
        print(f"    ✅ moved back to {target}")
        return True
    except Exception as e:
        print(f"    ⚠️ md 写入失败: {e}")
        return False


def backfill_one_sync(md_path, source_url, vault_root):
    """sync 包装, 让 list 顺序处理能跑."""
    return asyncio.run(backfill_one_async(md_path, source_url, vault_root))


def find_targets(md_root):
    """找 _to_backfill_0731 下所有 md 文件."""
    out = []
    if not os.path.isdir(md_root):
        return out
    for fp in sorted(Path(md_root).rglob("*.md")):
        fp = str(fp)
        try:
            txt = open(fp).read()
        except Exception:
            continue
        m = re.search(r'source_url:\s*"?(https?://[^"\s]+)', txt)
        if not m:
            continue
        out.append((fp, m.group(1)))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--md-root", default=os.path.expanduser("~/Documents/steven_vault/_to_backfill_0731"))
    p.add_argument("--vault-root", default=os.path.expanduser("~/Documents/steven_vault"))
    p.add_argument("--max", type=int, default=999)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    
    targets = find_targets(a.md_root)
    print(f"=== 待补: {len(targets)} 个 (md-root={a.md_root}) ===\n")
    
    if a.dry_run:
        for i, (fp, url) in enumerate(targets[:a.max], 1):
            print(f"  [{i}] {os.path.basename(fp)}")
            print(f"        {url}")
        return
    
    n_ok = n_fail = 0
    _consecutive_fails = 0  # A2e: 连续失败计数
    _MAX_CONSECUTIVE_FAILS = 3  # 连续失败 3 条 → 退出 (避免空跑)
    _POST_FAIL_SLEEP = 60  # 每条失败后等 60s 让网络/Groq 恢复
    # A5 (2026-08-01): 删掉 A2d 加的 groq_probe 预探测
    # 原因: mp3 压缩 (A3) + max-time 300s (A4) 后, 真实转录本身就 ~90s 必出结果
    #   → 不需要额外 4s 探测 (省 18 条 × 4s = 72s)
    #   → 即便网络抽风, transcribe_groq retry 已覆盖 (网络层 + HTTP 5xx 双 retry)
    for i, (fp, url) in enumerate(targets[:a.max], 1):
        print(f"\n[{i}/{min(len(targets), a.max)}] {os.path.basename(fp)}")
        print(f"  URL: {url}")
        try:
            _ok = backfill_one_sync(fp, url, a.vault_root)
        except Exception as e:
            print(f"  ⚠️ 顶层错误: {e}")
            _ok = False
        if _ok:
            n_ok += 1
            _consecutive_fails = 0
        else:
            n_fail += 1
            _consecutive_fails += 1
            # A2e: 失败后强制 sleep, 给网络/Groq 恢复时间
            print(f"  [backoff] 失败后等 {_POST_FAIL_SLEEP}s 让网络/Groq 恢复...", flush=True)
            import time as _t_b
            _t_b.sleep(_POST_FAIL_SLEEP)
            # 连续失败达到阈值 → 退出
            if _consecutive_fails >= _MAX_CONSECUTIVE_FAILS:
                print(f"\n❌ 连续 {_consecutive_fails} 条失败, 退出避免空跑 (已跑 {n_ok} 成功 / {n_fail} 失败)")
                break
    print(f"\n=== 完成: 成功 {n_ok} / 失败 {n_fail} ===")


if __name__ == "__main__":
    main()
