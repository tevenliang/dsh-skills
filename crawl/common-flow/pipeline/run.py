import sys, os
_here = os.path.dirname(os.path.abspath(__file__))
while _here and not os.path.exists(os.path.join(_here, "_bootstrap.py")):
    _p = os.path.dirname(_here)
    if _p == _here:
        _here = None
        break
    _here = _p
if _here:
    sys.path.insert(0, _here)
import _bootstrap

#!/usr/env python3
# -*- coding: utf-8 -*-
"""
pipeline/run.py — ominicrawl 流水线路由 (ominicrawl v1)

职责: 把「来源层(crawl.py) 给的 URL / 平台 + 日期」路由到对应 tools/<平台> fetcher,
然后按平台执行流水线, 最后发布到 vault (subscription/)。

两类入口:
  process_url(url, dest)
      URL 型平台 (bilibili/douyin/xiaohongshu/generic/wechat)
      dest = {"mode": "clip"|"watchlist", "date": "260709"(watchlist 用)}
      流程: tools/<p>.crawl(url, tmp) → push(单篇 vault subscription/) → [summarize_and_insert]
  process_search(platform, date_yymmdd)
      搜索型平台 (boss/jd/linkedin/tieba)
      流程: tools/<p>.crawl_batch(date) → 每条 push_aggregated_batch (落 vault, 无 LLM 总结)

流水线细则 (v5):
  bilibili/douyin → 转录(已在 fetcher 内完成) + 总结 + 推 vault
  xiaohongshu      → OCR(已在 fetcher 内下载图) + 总结 + 推 vault
  generic(web)     → 总结 + 推 vault
  wechat           → 推 vault (不总结)
  boss/jd/li/tieba → opencli 原始单文件 (不总结)

落点: $VAULT/subscription (publish_vault, 双平台回退):
  clip/单条 → $VAULT/subscription/<平台>/<博主>/hot.md
  watchlist/搜索 → $VAULT/subscription/<平台>/<博主>/ (hot + 按月归档)
"""
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
for _p in (str(SKILL_DIR), str(SKILL_DIR / "common"), str(SKILL_DIR / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.registry import is_enabled, can_monitor
from common.clipboard import canonical_key
from common.publish_vault import push, push_aggregated_batch
from common.summarize import summarize

try:
    import yaml
    _cfg = yaml.safe_load((SKILL_DIR / "config.yaml").read_text(encoding="utf-8")) or {}
except Exception:
    _cfg = {}

TZ = timezone(timedelta(hours=8))

URL_PLATFORMS = {"bilibili", "douyin", "xiaohongshu", "generic", "wechat"}
SEARCH_PLATFORMS = {"boss", "jd", "linkedin", "tieba"}
# 需要 LLM 总结(总结注入 md 顶部)的平台
SUMMARIZE_PLATFORMS = {"bilibili", "douyin", "generic"}
# 注 (2026-07-15): 用户关闭了 xhs 的 LLM 总结 — 现在小红书"只爬原文档"
# OCR + summarize 都跳过了。xhs 仍走 tool fetch → build_note_blocks 推 hot doc.

PLATFORM_LABELS = {
    "wechat": "微信公众号", "xiaohongshu": "小红书", "bilibili": "B站",
    "douyin": "抖音", "generic": "通用", "boss": "Boss", "jd": "京东",
    "linkedin": "领英", "tieba": "贴吧",
}

# ── Universal opencli fallback (2026-07-22) ──
# 任意平台 fetcher 返回正文过少时，用 opencli 浏览器渲染重抓。

MIN_BODY_CHARS = 30

def _md_body_len(md_path):
    try:
        text = Path(md_path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return 0
    if text.startswith("---\n"):
        idx = text.find("\n---\n", 4)
        if idx >= 0:
            text = text[idx + 6:]
    lines = text.splitlines()
    body_lines = [ln for ln in lines
                  if ln.strip() and not (ln.startswith("**") and "**: " in ln)]
    return len("\n".join(body_lines).strip())


def _opencli_fallback(url, tmp_dir):
    try:
        from common.opencli_bridge import fetch_rendered
    except ImportError:
        from opencli_bridge import fetch_rendered
    print("   [opencli 回退] 浏览器渲染: " + url[:70])
    md_text, _html = fetch_rendered(url, wait_secs=8, timeout=300)
    if not md_text or len(md_text.strip()) < MIN_BODY_CHARS:
        raise RuntimeError("opencli 也返回空内容")
    title = None
    for line in md_text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            title = line[2:].strip()
            break
    if not title:
        title = md_text.split("\n")[0][:60].strip() or "opencli-article"
    md_path = os.path.join(tmp_dir, "opencli.md")
    open(md_path, "w", encoding="utf-8").write(md_text)
    return title, md_path


def detect_platform(url):
    return canonical_key(url)[0]


def _import_tool(plat):
    return importlib.import_module(f"tools.{plat}")


def _yymmdd_now():
    return datetime.now(TZ).strftime("%y%m%d")


def _summarize_and_insert(vault_file_path, md_path=None):
    """调 summarize.py (GLM 主题-bullet) 并注入到 vault 文件。

    2026-07-23 修复: vault_file_path 必须是 vault 里持久化的 .md 文件路径，
    不是 tmp_dir 里会被 shutil.rmtree 删掉的临时文件。
    md_path 仅作 fallback（当 vault_file_path 不存在时）。
    """
    target = vault_file_path
    if not target or not os.path.exists(target):
        if md_path and os.path.exists(md_path):
            target = md_path
        else:
            print(f"   ⚠️ 总结跳过: vault 文件不存在 ({vault_file_path})")
            return
    try:
        obj = summarize(target)
    except Exception as e:
        print(f"   ⚠️ 总结跳过: {e}")
        return
    summary = obj.get("summary", "")
    topics = obj.get("topics", [])
    if not summary or not topics:
        print("   ⚠️ 总结 JSON 缺 summary/topics, 跳过")
        return
    n_topics = len(topics) if isinstance(topics, list) else 0
    try:
        from common.summarize import inject_summary_to_md
        inject_summary_to_md(target, obj, overwrite=True)
        # 2026-07-26: 打印相对 vault 的完整路径, 让监控日志能核对下载了哪个文件
        _vr = os.path.expanduser(os.environ.get("VAULT", "/Users/tianwenliang/Documents/steven_vault"))
        _rel = os.path.relpath(target, _vr) if target.startswith(_vr) else os.path.basename(target)
        print(f"   📝 总结完成: 📌 {summary[:30]}... ({n_topics} 条要点) → {_rel}")
    except Exception as e:
        print(f"   ⚠️ 总结注入失败: {e}")


def process_url(url, dest=None, author=None, title_override=None):
    """处理单个 URL。dest={"mode","date"}。

    返回 (url, obj) 或 None(跳过/失败)。
    """
    dest = dest or {"mode": "clip"}
    mode = dest.get("mode", "clip")
    plat = detect_platform(url)
    label = PLATFORM_LABELS.get(plat, plat)

    if mode == "watchlist" and not can_monitor(plat):
        print(f"  ⏭️  {label} monitor=false, 跳过 watchlist 监控")
        return None
    if not is_enabled(plat):
        print(f"  ⚠️  {label} 工具未启用 (crawl set-tool 可切换), 跳过")
        return None

    print(f"\n🌐 [{label}] {url[:80]}")
    tmp = tempfile.mkdtemp(prefix="ominicrawl_")
    try:
        mod = _import_tool(plat)
        ret = mod.crawl(url, tmp)
        if len(ret) == 4:
            title, fetched_author, md, images = ret
        elif len(ret) == 3:
            title, md, images = ret
            fetched_author = None
        else:
            raise RuntimeError(f"fetcher 返回值数量异常: {len(ret)}")
        # B1 fix (2026-07-16): fetcher 返回 (None, None, None, None) 表示跳过
        # (单条 BV -404/接口拒答), 不要让 Path(None) 炸出 TypeError
        if title is None or md is None:
            print(f"   ⏭️  fetcher 主动跳过 (title/md 为 None), 继续下一条")
            return None

        # ── 2026-07-22 Universal opencli fallback ──
        # 2026-07-26 修复: 抖音/B站正文短是设计预期(元数据/视频描述)，
        #   真实内容在 ASR 转录后，跳过 opencli fallback
        body_len = _md_body_len(md)
        if body_len < MIN_BODY_CHARS and plat not in ("douyin", "bilibili"):
            print(f"   ⚠️ 正文过少 (body={body_len}), 触发 opencli 回退")
            try:
                title, md = _opencli_fallback(url, tmp)
                images = None
            except Exception as e:
                print(f"   ⚠️ opencli 回退失败: {e}，保留 fetcher 结果")
        # ── fallback 结束 ──
        if author is None:
            author = fetched_author
        # 2026-07-22: 防御兜底 — fetcher (xhs-downloader 等) 抓不到真实数据时,
        # 会用 "未知标题"/"未知作者" 占位, 写进 notes 后会被发布成空条目.
        # 这种条目没意义, 直接跳过 (不写 notes).
        if (title or "").strip() in ("未知标题", "未命名", "unnamed", "(无标题)"):
            print(f"   ⏭️  标题为兜底值 ({title!r}), 跳过 (fetcher 抓不到真实标题)")
            return None
        if (author or "").strip() in ("未知作者", "未分类", "unknown"):
            print(f"   ⏭️  作者为兜底值 ({author!r}), 跳过")
            return None
        if title_override:
            title = title_override
        print(f"   📰 {title}")
        if author:
            print(f"   ✍️  {author}")

        if mode == "watchlist":
            # 2026-07-22: 直接追加到 vault hot.md，不用 notes/ 中间目录。
            # append_single_to_hot 内部处理去重(dedup by source_url)和图片物化，
            # 直接落 vault/subscription/<plat>-hot.md（含当月 hot + 历史月归档）。
            # tmp_dir 在 finally 里自动清理，无需手动搬文件。
            from common.publish_vault import append_single_to_hot
            vault_path, meta = append_single_to_hot(plat, md, images, title=title, author=author)
            # 2026-07-23 fix: 总结注入 vault 持久文件（不再是 tmp_dir 会被删的临时文件）
            if vault_path and plat in SUMMARIZE_PLATFORMS:
                _summarize_and_insert(vault_path, md)
            return vault_path, meta
        else:
            url, obj = push(md, images, title, platform=plat, author=author)
            print(f"   ✅ vault: {url}")
            if url and plat in SUMMARIZE_PLATFORMS:
                _summarize_and_insert(url, md)  # push 返回的 url 就是 vault 文件路径
            return url, obj
    except Exception as e:
        print(f"   ❌ 失败: {e}")
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def process_search(platform, date_yymmdd=None):
    """搜索型平台: 跑 crawl_batch → 逐条 push_aggregated_batch (落 vault, 不总结)。"""
    if platform not in SEARCH_PLATFORMS:
        raise ValueError(f"process_search 仅支持搜索型平台: {platform}")
    if not is_enabled(platform):
        print(f"  ⚠️  {platform} 工具未启用, 跳过")
        return []
    date = date_yymmdd or _yymmdd_now()
    print(f"\n🔎 [{PLATFORM_LABELS.get(platform, platform)}] 搜索抓取 (date={date})")
    try:
        mod = _import_tool(platform)
        results = mod.crawl_batch(date_yymmdd)
    except Exception as e:
        print(f"   ❌ 搜索失败: {e}")
        return []
    # 2026-07-22: 直接追加到 vault hot.md，不用 notes/ 中间目录。
    from common.publish_vault import append_single_to_hot
    n_written = 0
    for item in results:
        # 兼容 3-tuple (title, md_path, images_dir) 和 4-tuple (title, author, md_path, images_dir)
        if len(item) == 4:
            title, author_item, md, images = item
        elif len(item) == 3:
            title, md, images = item
            author_item = None
        else:
            continue
        try:
            append_single_to_hot(platform, md, images, title=title, author=author_item)
            n_written += 1
        except Exception as e:
            print(f"   ⚠️ 发布失败 [{title[:30]}]: {e}")
    return [str(r) for r in results]


# ── watchlist 跑批末尾: 把 notes/ 重读成 items → 推永久 hot+monthly 双层 docx ──
def load_platform_items_from_notes(plat: str, plat_label: str = None) -> list:
    """从 notes/<plat>/ 重读全平台历史 → build_note_block → items list.

    既支持博主型目录 notes/<plat>/<blogger>/*.md, 也支持单条型
    notes/<plat>/*.md (例如 jd/linkedin 搜索型).
    """
    from common.paths import notes_dir, project_root, media_dir
    from common.summarize_markdown import build_note_block, build_note_blocks

    plat_dir = notes_dir() / plat
    if not plat_dir.exists():
        return []

    items = []
    err_count = 0
    for md_path in plat_dir.rglob("*.md"):
        # 跳过 _archive / hidden / 旧 push_aggregated 留下的 section.md 缓冲
        if md_path.name.startswith(".") or md_path.name.startswith("_archive"):
            continue
        if md_path.name == "section.md":
            continue
        # 过滤旧格式目录（含 "·" 的目录，如 "AI · AI生产力"）
        # 这些是旧版 xhs-downloader 生成的，title 通常是 "未命名笔记"
        parts = md_path.parts
        if any("·" in p for p in parts):
            continue
        try:
            # 跳过 title 为 "未命名笔记" 的旧文件（opencli browser 方案失败残留）
            from common.summarize_markdown import parse_frontmatter
            fm = parse_frontmatter(md_path)
            if (fm.get("title") or "").strip() == "未命名笔记":
                continue
            # 用 build_note_blocks (plural): 含职位/结果表格的 notes (linkedin/jd/boss/tieba
            # 搜索型) 每行解析为独立 item; 其他 1 个文件 1 个 item.
            blocks = build_note_blocks(md_path)
            for block in blocks:
                # 2026-07-22: 防御兜底 — 老 fetcher 跑批残留的 "未知标题"/"未知作者"
                # 在 ingest 阶段已修过 (process_url 跳过), 这里再加一道防历史脏数据.
                if (block.get("title") or "").strip() in ("未知标题", "未命名", "unnamed", "(无标题)"):
                    continue
                if (block.get("author") or "").strip() in ("未知作者", "未分类", "unknown"):
                    continue
                block["md_path"] = str(md_path)
                # images_dir: 以 md 文件位置为基准。
                # 小红书/抖音/B站/京东/领英: 图片在 md 同级 images/<note_id>/ 下，用 md.parent。
                # 贴吧: 图片在 media/tieba/ 下，用 media_dir() / "tieba"。
                if plat in ("xiaohongshu", "douyin", "bilibili", "jd", "linkedin", "boss"):
                    block["images_dir"] = str(md_path.parent)
                else:  # tieba 等
                    block["images_dir"] = str(media_dir())
                items.append(block)
        except Exception as e:
            err_count += 1
            if err_count <= 3:
                print(f"    ⚠️  {md_path.name}: {e}")
    return items


WATCHLIST_PLATFORMS = ["douyin", "bilibili", "xiaohongshu", "boss", "jd", "linkedin", "tieba"]


def _ensure_summaries_for_platform(plat, summary_window_days=30):
    """对 bilibili/douyin/generic 平台, 给 summary window 内且无 ## 总结 段的 md
    调 LLM 生成 summary+topics, 注入到 md 末尾. 注入后 build_note_block
    能从 md 文本里自然读到 core/speedread/quotes, push 阶段无需再注入.

    注意: summary window 是 LLM 注入窗口, 与 publish 阶段的 hot(自然月) 切分
    是两个独立概念, 不要混用。

    - SUMMARIZE_PLATFORMS 以外的平台直接 return
    - 已存在 ## 总结 段跳过 (避免重复调 LLM)
    - 太短 (<100 字正文) 跳过
    - 单条 LLM 异常不影响整体, 仅打印警告

    Returns: (n_injected, n_skipped, n_err)
    """
    if plat not in SUMMARIZE_PLATFORMS:
        return 0, 0, 0
    from common.paths import notes_dir, project_root, media_dir
    from common.summarize import summarize, inject_summary_to_md, has_summary_section
    from datetime import date, timedelta
    n_inj = n_skip = n_err = 0
    cutoff = (date.today() - timedelta(days=summary_window_days)).strftime("%Y%m%d")
    plat_dir = notes_dir() / plat
    if not plat_dir.exists():
        return 0, 0, 0
    label = PLATFORM_LABELS.get(plat, plat)
    targets = []
    for md_path in plat_dir.rglob("*.md"):
        if md_path.name.startswith(".") or md_path.name.startswith("_archive"):
            continue
        if md_path.name == "section.md":
            continue
        if any("·" in part for part in md_path.parts):
            continue
        # 只补 hot window 内 (避免一次性为上千条历史笔记花 API 钱)
        # 用文件名首段 yymmdd 粗筛 (格式: 260715-标题.md)
        import re as _re
        m = _re.match(r"(\d{6})-", md_path.name)
        if not m:
            continue
        yymmdd = m.group(1)
        # 转成 YYYYMMDD
        yyyy = "20" + yymmdd[:2]
        yyyymmdd = yyyy + yymmdd[2:]
        if yyyymmdd < cutoff:
            continue
        if has_summary_section(md_path):
            n_skip += 1
            continue
        targets.append(md_path)
    if not targets:
        return 0, n_skip, 0
    print(f"  🤖 [{label}] 给 {len(targets)} 篇笔记补 LLM 总结 ...")
    for md_path in targets:
        try:
            obj = summarize(md_path)
            if inject_summary_to_md(md_path, obj):
                n_inj += 1
                print(f"     ✅ {md_path.parent.name}/{md_path.name[:50]}")
        except Exception as e:
            n_err += 1
            if n_err <= 3:
                print(f"     ⚠️  {md_path.parent.name}/{md_path.name[:50]}: {e}")
    return n_inj, n_skip, n_err


def finalize_documents(platforms=None, summary_window_days: int = 30) -> dict:
    """watchlist 跑批末尾: 重读 notes → 推永久 hot(当前自然月)+monthly 双层 docx.

    summary_window_days 只用于 LLM 总结注入窗口 (与 hot 切分无关, hot 用自然月).
    返回 {plat: {"hot": (url, obj), "monthly": {YYYY-MM: (url, obj)}}, ...}
    """
    if platforms is None:
        platforms = WATCHLIST_PLATFORMS
    print(f"\n📦 finalize: 重新同步永久 docx (hot=当前自然月 + monthly, summary_window={summary_window_days}d)")
    results = {}
    for plat in platforms:
        try:
            # 先给 hot window 内缺总结的笔记补 LLM 总结 (注入到 md, 自包含)
            n_inj, n_skip, n_err = _ensure_summaries_for_platform(plat, summary_window_days=summary_window_days)
            if n_inj or n_skip:
                print(f"  🤖 [{PLATFORM_LABELS.get(plat, plat)}] 总结补齐: 注入 {n_inj} 篇, 跳过 {n_skip} 篇, 失败 {n_err}")
            items = load_platform_items_from_notes(plat)
            if not items:
                print(f"  ⏭️  {plat}: 无 notes, 跳过")
                continue
            n_hot_est = sum(1 for it in items
                            if (it.get("publish_date") or "").isdigit() and len(it.get("publish_date") or "") == 8)
            res = push_aggregated_batch(plat, items)
            n_monthly = len(res["monthly"])
            results[plat] = res
            print(f"  ✅ {plat}: hot obj={'已更新' if res['hot'] else 'skip'}, monthly={n_monthly} months, items={len(items)}")
        except Exception as e:
            print(f"  ⚠️  {plat}: {e}")
    return results


if __name__ == "__main__":
    # 自检命令: python run.py <url>
    if len(sys.argv) > 1:
        print(process_url(sys.argv[1], {"mode": "clip"}))
    else:
        print("URL_PLATFORMS:", URL_PLATFORMS)
        print("SEARCH_PLATFORMS:", SEARCH_PLATFORMS)
