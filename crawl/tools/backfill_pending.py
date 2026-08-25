#!/usr/bin/env python3
"""
backfill_pending.py — 跨 batch 自动 retry pending wav (2026-08-03 治本)

设计:
- 扫 state/pending_audio/{bilibili,douyin}/ 下所有 wav/mp3
- 对每个文件: 找对应 vault md → 切片 (>8min) → 调 transcribe() → 写回 md → 删 wav
- 集成点: supervisor.cmd_all() 在 watchlist 之前自动调一次, 让昨天/上次遗留 wav 消化

关键阈值:
- 切片阈值 480s (8 分钟): Groq Cloudflare 524 临界点 ~12 分钟, 留 4 分钟 buffer
- 跳过条件: md ## 转录 section 已 > 100 字
- 删除条件: 转录成功 (>0 字)

用法:
  python3 tools/backfill_pending.py --dry-run                       # 列出待补的 wav
  python3 tools/backfill_pending.py --max 3                        # POC 3 条
  python3 tools/backfill_pending.py                                # 全跑
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

CRAWL_ROOT = Path(__file__).resolve().parent.parent

# 2026-08-07: backfill 不仅是补转录, 还要补 GLM 总结, 让 backfill 后落库的 md 是完整笔记
sys.path.insert(0, str(CRAWL_ROOT / "common-summary"))
from summarize import summarize, inject_summary_to_md, has_summary_section
# crawl 3.1.0: VM 是唯一 ASR 路径, backfill 也走 VM handoff 而非本地 groq
sys.path.insert(0, str(CRAWL_ROOT / "tools"))
try:
    from handoff_vm import handoff_to_vm
except Exception:
    handoff_to_vm = None
PENDING_AUDIO_DIR = CRAWL_ROOT / "state" / "pending_audio"
VAULT_DEFAULT = Path(os.path.expanduser("~/Documents/steven_vault"))

# 切片阈值 8 分钟 (Groq 524 临界点 ~12 分钟, 留 4 分钟 buffer)
SLICE_THRESHOLD_SEC = 480
SLICE_LEN_SEC = 240


def find_md_for_bvid(vault_root: Path, platform: str, bvid: str):
    """根据 bvid 在 vault subscription/{platform}/ 下找对应 md.

    查找规则:
    1. 扫所有 md, 找 frontmatter source_url 含 bvid 的 (不靠文件名, 因为命名有 _1/_2 后缀)
    2. 多个匹配时, 优先选 ## 转录为 0 字的最新版本 (空正文是待 backfill 目标)
    3. 如果都 > 0 字, 取最近修改的 (但应该跳过, 已转录过)
    """
    sub_dir = vault_root / "subscription" / platform
    if not sub_dir.is_dir():
        return None

    candidates = []
    for md in sub_dir.rglob("*.md"):
        try:
            content = md.read_text()
        except Exception:
            continue
        # 只看 frontmatter 里的 source_url 是否含 bvid (避免正文误中)
        m = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if not m:
            continue
        frontmatter = m.group(1)
        if bvid not in frontmatter:
            continue
        # 看 ## 转录 section 字数
        tm = re.search(r"##\s*转录\s*\n+(.*?)(?=\n##|\Z)", content, re.DOTALL)
        tlen = len(tm.group(1).strip()) if tm else 0
        candidates.append((md, tlen, md.stat().st_mtime))

    if not candidates:
        return None
    # 优先空正文 (tlen=0) + 最近修改; 都没有就返回最近修改的
    empty = [c for c in candidates if c[1] == 0]
    if empty:
        return max(empty, key=lambda c: c[2])[0]
    return max(candidates, key=lambda c: c[2])[0]


def md_already_transcribed(md_path: Path) -> bool:
    """检查 md 的 ## 转录 section 是否已有 >100 字."""
    try:
        txt = md_path.read_text()
    except Exception:
        return False
    m = re.search(r"##\s*转录\s*\n+(.*?)(?=\n##|\Z)", txt, re.DOTALL)
    if not m:
        return False
    return len(m.group(1).strip()) > 100


def write_transcript_to_md(md_path: Path, transcript: str) -> None:
    """把转录文字写入 md 的 ## 转录 section (有则替换, 无则追加)."""
    txt = md_path.read_text()
    new_section = f"## 转录\n\n{transcript.strip()}\n\n"

    if re.search(r"^##\s*转录\s*$", txt, re.MULTILINE):
        txt = re.sub(
            r"##\s*转录\s*\n+.*?(?=\n##|\Z)",
            new_section.rstrip() + "\n\n",
            txt,
            count=1,
            flags=re.DOTALL,
        )
    else:
        txt = txt.rstrip() + "\n\n" + new_section

    md_path.write_text(txt)


def get_wav_duration(wav_path: Path) -> float:
    """用 ffprobe 取 wav 时长 (秒)."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(wav_path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def slice_wav(wav_path: Path, slice_len_sec: int = SLICE_LEN_SEC):
    """切 wav 为多段 (返回切片文件路径列表)."""
    duration = get_wav_duration(wav_path)
    if duration <= slice_len_sec:
        return [wav_path]

    slices = []
    n_slices = int(duration // slice_len_sec) + (1 if duration % slice_len_sec > 0 else 0)
    out_dir = wav_path.parent / f"_slices_{wav_path.stem}"
    out_dir.mkdir(exist_ok=True)

    for i in range(n_slices):
        start = i * slice_len_sec
        out = out_dir / f"{wav_path.stem}_part{i+1:02d}.wav"
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-i", str(wav_path),
             "-ss", str(start),
             "-t", str(slice_len_sec),
             "-c", "copy",
             str(out)],
            capture_output=True, timeout=60,
        )
        if r.returncode == 0 and out.exists() and out.stat().st_size > 0:
            slices.append(out)
        else:
            print(f"    ⚠️ 切片失败: {out.name} (rc={r.returncode})")

    return slices


def cleanup_slices(slices):
    """清理切片临时文件 + 切片目录."""
    out_dirs = set()
    for s in slices:
        try:
            s.unlink()
        except Exception:
            pass
        if "_slices_" in str(s.parent):
            out_dirs.add(s.parent)
    for d in out_dirs:
        try:
            d.rmdir()
        except Exception:
            pass


def transcribe_one(wav_path: Path, crawl_root: Path):
    """转录单个 wav 文件 (调用 crawl 的 transcribe)."""
    sys.path.insert(0, str(crawl_root / "common-asr"))
    from transcribe import transcribe

    text, src = transcribe(str(wav_path))
    return text or "", src or "unknown"


def extract_meta_from_md(md_path: Path):
    """从 md frontmatter 提取 handoff 需要的 meta 字段 (title/author/source_url/publish_date)."""
    try:
        txt = md_path.read_text(encoding="utf-8")
    except Exception:
        return {}
    m = re.match(r"^---\s*\n(.*?)\n---", txt, re.DOTALL)
    if not m:
        return {}
    fm = m.group(1)
    meta = {}
    for key in ("title", "author", "source_url", "publish_date"):
        pat = re.compile("^" + re.escape(key) + r":\s*(.+?)\s*$", re.MULTILINE)
        mm = pat.search(fm)
        if mm:
            meta[key] = mm.group(1).strip()
    return meta


def process_one(platform: str, audio_path: Path, vault_root: Path, crawl_root: Path,
                slice_threshold_sec: int = SLICE_THRESHOLD_SEC):
    """处理单个 pending wav. 返回 (success, message).

    crawl 3.1.0: VM 是唯一 ASR 路径, backfill 不再本地 groq 转录, 改为:
      - md 已转录(>100字): wav 冗余, 直接删 (设计本就转录成功后删 wav)
      - md 空正文: handoff 到 VM 异步补转录, 成功后删本地 wav
    """
    bvid = audio_path.stem

    md_path = find_md_for_bvid(vault_root, platform, bvid)
    if not md_path:
        # 无对应 md, 保留 wav 不删 (避免丢数据)
        return False, f"找不到对应 md ({platform}/{bvid}), 保留 wav"

    print(f"  📄 md: {md_path.relative_to(vault_root)}")

    if md_already_transcribed(md_path):
        # 冗余 wav → 删除
        try:
            audio_path.unlink()
            return True, "md 已转录, 删冗余 wav"
        except Exception as e:
            return False, f"删冗余 wav 失败: {e}"

    # 空正文 → handoff VM 异步补转录 (VM 会转录+总结+publish 覆盖 md)
    if handoff_to_vm is None:
        return False, "handoff_to_vm 未加载, 跳过 (保留 wav)"
    meta = extract_meta_from_md(md_path)
    # douyin wav 名 douyin_<aweme>, video_id 取数字部分避免双重前缀
    video_id = bvid.split("_", 1)[1] if (platform == "douyin" and "_" in bvid) else bvid
    print(f"  🔼 handoff VM 补转录 ...")
    try:
        ok = handoff_to_vm(
            str(audio_path), platform, video_id,
            title=meta.get("title", ""),
            author=meta.get("author", ""),
            source_url=meta.get("source_url", ""),
            publish_date=meta.get("publish_date", ""),
            desc="",
            timeout=180,
        )
    except Exception as e:
        return False, f"handoff VM 异常: {str(e)[:120]}"
    if not ok:
        return False, "handoff VM 失败, 保留 wav"
    # handoff 成功, 删本地冗余 wav (VM 已持有副本)
    try:
        audio_path.unlink()
        return True, "已 handoff VM 异步补转录, 删本地 wav"
    except Exception as e:
        return True, f"handoff 成功但删本地 wav 失败: {e}"


def main():
    p = argparse.ArgumentParser(description="backfill pending wav (跨 batch retry)")
    p.add_argument("--vault", default=str(VAULT_DEFAULT))
    p.add_argument("--crawl-root", default=str(CRAWL_ROOT))
    p.add_argument("--max", type=int, default=None, help="最多处理几个 wav (POC 用)")
    p.add_argument("--platform", choices=["bilibili", "douyin"], default=None,
                   help="只处理某个平台 (默认全部)")
    p.add_argument("--dry-run", action="store_true", help="只列出待处理 wav, 不真转录")
    p.add_argument("--slice-threshold", type=int, default=SLICE_THRESHOLD_SEC,
                   help=f"切片阈值 (秒), 默认 {SLICE_THRESHOLD_SEC}")
    args = p.parse_args()

    vault_root = Path(args.vault)
    crawl_root = Path(args.crawl_root)

    if not PENDING_AUDIO_DIR.is_dir():
        print(f"❌ PENDING_AUDIO_DIR 不存在: {PENDING_AUDIO_DIR}")
        return 1

    platforms = [args.platform] if args.platform else ["bilibili", "douyin"]
    pending_raw = []
    for plat in platforms:
        plat_dir = PENDING_AUDIO_DIR / plat
        if not plat_dir.is_dir():
            continue
        for audio in sorted(plat_dir.iterdir()):
            if audio.suffix in (".wav", ".mp3"):
                pending_raw.append((plat, audio))

    # 去重: 同一 bvid 多个文件只留一个, 优先 wav (wav > mp3)
    seen = {}
    for plat, audio in pending_raw:
        bvid = audio.stem
        if bvid not in seen:
            seen[bvid] = (plat, audio)
        else:
            cur = seen[bvid][1]
            if audio.suffix == ".wav" and cur.suffix == ".mp3":
                seen[bvid] = (plat, audio)
            elif audio.suffix == cur.suffix and audio.stat().st_size > cur.stat().st_size:
                seen[bvid] = (plat, audio)
    pending = sorted(seen.values(), key=lambda x: x[1].name)

    print(f"=== 待 backfill: {len(pending)} 个音频 ===\n")
    for plat, audio in pending:
        size_mb = audio.stat().st_size / 1024 / 1024
        bvid = audio.stem
        md = find_md_for_bvid(vault_root, plat, bvid)
        if md and md_already_transcribed(md):
            md_status = "已转录"
        elif md:
            md_status = "空正文"
        else:
            md_status = "❌ 无 md"
        print(f"  [{plat}] {audio.name} ({size_mb:.1f}MB) → {md_status}")
        if md:
            print(f"        md: {md.relative_to(vault_root)}")

    if args.dry_run:
        if args.max:
            print(f"\n--max {args.max}: 本次会补 {min(len(pending), args.max)} 条")
        else:
            print(f"\n本次会补全部 {len(pending)} 条")
        return 0

    targets = pending[:args.max] if args.max else pending
    n_ok = n_fail = 0
    for i, (plat, audio) in enumerate(targets, 1):
        print(f"\n[{i}/{len(targets)}] 🔄 {plat}/{audio.name}")
        try:
            ok, msg = process_one(plat, audio, vault_root, crawl_root,
                                  slice_threshold_sec=args.slice_threshold)
            if ok:
                n_ok += 1
                print(f"  ✅ 成功: {msg}")
            else:
                n_fail += 1
                print(f"  ⚠️ 跳过/失败: {msg}")
        except Exception as e:
            n_fail += 1
            print(f"  ❌ 异常: {str(e)[:200]}")

    print(f"\n=== 完成: 成功 {n_ok} / 失败 {n_fail} / 总 {len(targets)} ===")
    return 0 if n_fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
