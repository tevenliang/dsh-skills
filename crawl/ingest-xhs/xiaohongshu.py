import sys, os, re
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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/xiaohongshu.py — 小红书工具层 (ominicrawl v3.1, 2026-07-16)

修复记录：
  2026-07-16: xhs read API 触发滑块验证码, 详情抓取改用 xhs-downloader 方案
  - user-posts(列表): 仍走 xhs-cli API (列表正常, 不撞风控)
  - detail(详情): 走 xhs-downloader (XHS-Downloader 库 + cookie 文件),
    真实页面渲染, 与 clip 单篇下载同一套, 不触发 xhs-cli 的滑块验证码

架构：
  ┌──────────────────┬──────────────────────────────┬────────────────────┐
  │ 入口             │ 工具                         │ 调用方式           │
  ├──────────────────┼──────────────────────────────┼────────────────────┤
  │ crawl(url)       │ xhs-downloader wrapper       │ subprocess + venv  │
  │ (clip / 单条)    │ (single_extract.py)          │                    │
  ├──────────────────┼──────────────────────────────┼────────────────────┤
  │ crawl_batch()    │ xhs-cli user-posts (列表)    │ xhs CLI → note list│
  │ (watchlist 监控) │ + xhs-downloader (详情)      │ 真实页面, 绕过验证码│
  └──────────────────┴──────────────────────────────┴────────────────────┘
  说明: 详情阶段不做日期过滤, 由 dedup(下载前) 保证幂等, 绝不删除已落盘文件.
"""
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import subprocess
# 2026-07-29: macOS fork EAGAIN (Errno 35) 重试 — xhs 整阶段 [Errno 35] 失败修复
import sys as _sys
_sys.path.insert(0, str(__file__).rsplit("/", 2)[0])  # common_supervisor 可导入
from common_supervisor._eagain_retry import run_with_retry as _xhs_run_with_retry
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ──────────── 常量 ────────────
SKILL_ROOT = Path.home() / ".agents" / "skills" / "crawl"

# clip 工具: xhs-downloader wrapper
XHS_DOWNLOADER = Path.home() / ".codex" / "vendor_imports" / "xhs-downloader"
HELPER = XHS_DOWNLOADER / "single_extract.py"
PYTHON_VENV = XHS_DOWNLOADER / ".venv" / "bin" / "python3"

# watchlist 工具
XHS_CLI = os.environ.get("XHS_CLI", str(Path.home() / ".local" / "bin" / "xhs"))

TZ = timezone(timedelta(hours=8))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# ──────────── opencli 辅助 ────────────



def _note_id_ts(note_id):
    """MongoDB ObjectID 前 4 字节 = Unix 秒 (XHS 创建时间). 返回 (ts_int, dt_str)."""
    if not note_id or len(note_id) < 8:
        return 0, ""
    try:
        ts = int(note_id[:8], 16)
        dt = datetime.fromtimestamp(ts).strftime("%y%m%d-%H:%M")
        return ts, dt
    except Exception:
        return 0, ""


def _xhs_download_detail(note_url, out_dir, timeout=60, max_retries=3):
    """xhs-downloader 单篇抓取 (与 clip 单篇下载同一套: XHS-Downloader 库 + cookie 文件).
    走真实页面渲染, 不走 xhs-cli HTTP API, 因此不触发滑块验证码.
    返回 single_extract.py 的 JSON dict:
      {ok,title,author,md_path,images_dir,downloads,note_id,publish_iso,info}

    2026-07-21:
    - timeout 180 → 240s (xhs 图片 CDN 偶发慢)
    - 增加 retry 2 次 (单次 timeout 不会雪崩, 优先快速失败)
    - 剥代理 (xhs 是国内端点)
    """
    _check_xhs_downloader_install()
    cmd = [str(PYTHON_VENV), str(HELPER), note_url, str(out_dir)]
    # 2026-07-21: 不再剥 HTTPS_PROXY — VPN 按域名自动路由
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                cwd=str(XHS_DOWNLOADER),
                start_new_session=True,
            )
            if r.returncode != 0:
                # xhs-downloader 内部失败, 但返回 JSON {ok:False, error:"..."}
                # 先尝试解析, 解析成功且 ok=False → 直接返回（不是网络问题, 重试无意义）
                last_line = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
                try:
                    obj = json.loads(last_line) if last_line.startswith("{") else None
                    if obj and obj.get("ok") is False and obj.get("error"):
                        return obj
                except Exception:
                    pass
                raise RuntimeError(
                    f"xhs-downloader exit {r.returncode}: "
                    f"stderr={r.stderr[:200]} stdout_tail={r.stdout[-300:]}"
                )
            last_line = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "{}"
            return json.loads(last_line)
        except subprocess.TimeoutExpired:
            last_err = RuntimeError(f"xhs-downloader timeout (>{timeout}s) attempt {attempt}")
            print(f"    WARN xhs-downloader 超时 attempt {attempt}/{max_retries}, 开启连常快速失败", flush=True)
            if attempt < max_retries:
                import signal, os
                try:
                    os.killpg(os.getpgid(r.pid), signal.SIGKILL)
                except Exception as ke:
                    pass
                time.sleep(3 * attempt)
        except (json.JSONDecodeError, IndexError) as e:
            raise RuntimeError(f"xhs-downloader parse failed: {e}; stdout={r.stdout[:200]}")
        except RuntimeError as e:
            last_err = e
            # 网络/timeout 类失败才重试, 解析/逻辑失败抛出
            err_s = str(e)
            if "timeout" in err_s or "Connection" in err_s or "ssl" in err_s.lower():
                if attempt < max_retries:
                    print(f"    WARN xhs-downloader 网络失败 attempt {attempt}, 重试: {err_s[:120]}", flush=True)
                    time.sleep(2 * attempt)
                    continue
            raise
        except Exception as e:
            last_err = RuntimeError(f"xhs-downloader failed: {e}")
            if attempt < max_retries:
                time.sleep(2)
                continue
            raise last_err
    raise last_err or RuntimeError("xhs-downloader failed after retries")


def _xhs_cleanup_detail(creator_dir, res):
    """时间过滤/去重跳过时, 删掉刚下载的 md + images, 避免残留."""
    try:
        import shutil
        mp = res.get("md_path")
        if mp and Path(mp).exists():
            Path(mp).unlink()
        idir = res.get("images_dir")
        if idir and Path(idir).exists():
            shutil.rmtree(idir, ignore_errors=True)
    except Exception:
        pass


def _xhs_dedup_skip(note_id, plat_root):
    """全局 note_id dedup: 同篇被多博主抓到只存一份. 返回已存在的 md 路径或 None.
    2026-07-23: 落盘路径改为 vault subscription/，dedup 也查 vault（notes/ 已废弃）。"""
    vault_root = Path(os.environ.get("VAULT", "/Users/tianwenliang/Documents/steven_vault"))
    vault_plat = vault_root / "subscription" / "xiaohongshu"
    notes_plat = Path(plat_root) if isinstance(plat_root, str) else plat_root

    for plat in [vault_plat, notes_plat]:
        if not plat.exists():
            continue
        for existing in plat.rglob("*.md"):
            try:
                txt = existing.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if (f"explore/{note_id}" in txt
                    or f"uid: {note_id}" in txt
                    or f"note_id: {note_id}" in txt):
                return existing
    return None


def _fix_tags_line(ln: str) -> str:
    """把 xhs-downloader 产出的畸形 tags 行 'tags: ["a b c"]' 修正为 'tags: ["a", "b", "c"]'.
    已是正确逗号列表([a, b])或空列表([])则原样返回."""
    m = re.match(r'^tags:\s*(.*)$', ln, re.S)
    if not m:
        return ln
    val = m.group(1).strip()
    if val in ("", "[]"):
        return ln
    # 形态1: 单引号字符串里用空格/顿号粘连多个标签 -> 拆成列表
    qm = re.match(r'^\["(.*)"\]\s*$', val)
    if qm:
        inner = qm.group(1)
        toks = [t for t in re.split(r'[\s、]+', inner.strip()) if t]
        if len(toks) > 1:
            return "tags: [" + ", ".join('"%s"' % t for t in toks) + "]"
    # 形态2: 已是正确列表 -> 保留
    return ln


def _normalize_fm(fm: str) -> str:
    """frontmatter 规范化: ① 去掉重复 key(上游 xhs-downloader 已写 source_url,
    我们又在 _enrich_frontmatter 追加 -> 重复键会让 Obsidian 报 frontmatter 错误);
    ② 修正畸形的 tags 行. 仅作用于 --- 之间的文本, 不动正文."""
    out, seen = [], set()
    for ln in fm.split("\n"):
        km = re.match(r'^([A-Za-z_][\w-]*)\s*:', ln)
        if km:
            key = km.group(1)
            if key in seen:
                continue  # 丢弃重复键行
            seen.add(key)
            if key == "tags":
                ln = _fix_tags_line(ln)
        out.append(ln)
    return "\n".join(out)


def _enrich_frontmatter(md_path, note_id, note_url, res):
    """给 xhs-downloader 产出的 md 补 watchlist 字段 (uid/note_id/likes/...), 不破坏图片引用."""
    p = Path(md_path)
    if not p.exists():
        return
    text = p.read_text(encoding="utf-8")
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return
    pre, fm, body = parts[0], parts[1], parts[2]
    info = res.get("info") or {}

    # 先规范化已有 frontmatter(去重 source_url / 修正 tags), 避免叠加出新重复
    fm = _normalize_fm(fm)

    def _num(cn_key):
        v = info.get(cn_key)
        return _parse_count(v) if v not in (None, "") else None

    add = [f"uid: {note_id}", f"note_id: {note_id}"]
    if "source_url:" not in fm:
        add.append(f"source_url: {note_url}")
    likes = _num("点赞数量"); comments = _num("评论数量"); favorites = _num("收藏数量")
    if likes is not None: add.append(f"likes: {likes}")
    if comments is not None: add.append(f"comments: {comments}")
    if favorites is not None: add.append(f"favorites: {favorites}")
    tags = info.get("作品标签")
    if tags:
        tl = tags if isinstance(tags, list) else [tags]
        add.append("tags: [" + ", ".join(_yml_escape(str(t)) for t in tl if t) + "]")
    ip = info.get("IP属地") or info.get("ip_location")
    if ip:
        add.append(f"ip_location: {_yml_escape(str(ip))}")
    new_fm = fm.rstrip("\n") + "\n" + "\n".join(add) + "\n"
    p.write_text(pre + "---\n" + new_fm + "---\n" + body, encoding="utf-8")


def _process_one_note_api(note_id: str, note_url: str, creator_name: str,
                          creator_dir: Path, since_yymmdd: str | None = None,
                          display_title=None) -> tuple | None:
    """用 xhs-downloader 抓笔记详情 (与 clip 单篇下载同一套: XHS-Downloader 库 + cookie 文件),
    走真实页面渲染, 不触发 xhs-cli 的滑块验证码.

    流程 (非破坏性, 幂等):
      1) 全局 note_id dedup —— 下载【前】判断, 避免重复下载, 且绝不删除既有文件
      2) xhs-downloader 单篇抓取 (subprocess + venv)
      3) enrichment —— 补 uid/note_id/likes/comments/favorites/tags/ip_location

    返回 (title, author_name, md_path, images_dir) 或 None.

    重要: 详情阶段【不做日期过滤】。列表阶段(user-posts)已筛选近期笔记,
    重复运行由 dedup 保证幂等; 绝不能以 "日期过早" 为由删除已落盘文件
    (旧的 since_yymmdd 把 today 当 cutoff, 会误删全部历史笔记)。
    """
    from common.paths import notes_dir
    plat_root = notes_dir() / "xiaohongshu"
    creator_dir = Path(creator_dir)

    # 1) 全局 note_id dedup (下载前, 非破坏性)
    dup = _xhs_dedup_skip(note_id, plat_root)
    if dup is not None:
        rel = dup.relative_to(plat_root) if plat_root in dup.parents else dup.name
        print(f"    ⏭️  dedup: note_id {note_id[:16]}... 已存于 {rel}, 跳过")
        return None

    # 2) 下载详情 (xhs-downloader, 真实页面渲染, 不撞滑块)
    try:
        res = _xhs_download_detail(note_url, str(creator_dir), timeout=240)
    except Exception as e:
        print(f"    ERR xhs-downloader: {e}")
        return None
    if not res.get("ok"):
        print(f"    ERR xhs-downloader: {res.get('error', 'unknown')}")
        return None

    md_path = res.get("md_path")
    if not md_path or not Path(md_path).exists():
        print(f"    WARN xhs-downloader 无 md: {note_id[:16]}...")
        return None

    # 3) enrichment (总是执行, 幂等安全)
    _enrich_frontmatter(md_path, note_id, note_url, res)

    title = res.get("title") or display_title or "unnamed"
    author = res.get("author") or creator_name
    images_dir = res.get("images_dir")
    # API 没有返回 title/author（可能是私密/受限笔记），跳过以免污染 vault
    if title == "unnamed" and author == "未知作者":
        print(f"    ⏭️  note {note_id[:16]}... title/author 均为默认值，跳过")
        return None
    print(f"    OK {title[:24]}... (author={author})")
    return title, author, str(md_path), images_dir


def crawl_batch(date_yymmdd=None, limit_per_creator=None, read_sleep=None):
    """watchlist 入口:
       1. xhs-cli user-posts 拿博主笔记列表
       2. xhs-downloader 逐条抓详情 (与 clip 单篇下载同一套, 绕过滑块验证码)
       3. dedup(下载前) + enrichment 写 notes/xiaohongshu/<creator>/.md + images/

    注意: 详情阶段不做日期过滤, 重复运行由 dedup 保证幂等 (绝不删除已落盘文件).

    Envvars:
      XHS_LIMIT=2         每个博主最多 2 篇
      XHS_READ_SLEEP=1    每次 note 处理后 sleep 秒
    """
    if limit_per_creator is None:
        limit_per_creator = int(os.environ.get("XHS_LIMIT", "5")) or 5
    if read_sleep is None:
        try:
            read_sleep = float(os.environ.get("XHS_READ_SLEEP", "0") or 0)
        except ValueError:
            read_sleep = 0.0

    _check_xhs_cli_install()

    sys.path.insert(0, str(SKILL_ROOT))
    from common.feishu_watchlist import get_watchlist_markdown, parse_rows
    from common.paths import notes_dir

    try:
        md = get_watchlist_markdown()
    except Exception as e:
        print(f"  [xhs] 飞书 watchlist 读取失败: {e}")
        return []

    creators = parse_rows(md, "xiaohongshu")
    if not creators:
        print("  [xhs] watchlist ## 小红书 无博主")
        return []

    out = []
    for idx, (url, name, ocr_flag) in enumerate(creators):
            user_id = _extract_user_id(url)
            if not user_id:
                print(f"  ⚠️ [{name}] 无法从 URL 提取 user_id: {url}")
                continue
            print(f"\n  👤 xhs 博主: {name} ({user_id[:16]}...) [{idx+1}/{len(creators)}]")

            # user-posts 拿笔记列表
            try:
                r = _run_xhs_json(["user-posts", user_id], timeout=60)
            except Exception as e:
                print(f"  ❌ user-posts 失败 ({name}): {e}")
                continue

            notes = r.get("data", {}).get("notes") or []
            if not notes:
                print(f"  [空] {name} 无可见笔记")
                continue

            # limit 截断（XHS_LIMIT=5 ≈ 最近几天，兜底防止拉全量历史帖）
            # 注：日期过滤依赖 note_id 时间解析（小红书 Snowflake ID），暂不可靠，改用数量兜底
            if limit_per_creator and len(notes) > limit_per_creator:
                notes = notes[:limit_per_creator]

            for note in notes:
                note_id = note.get("note_id")
                xsec = note.get("xsec_token") or ""
                if not note_id:
                    continue

                note_url = f"https://www.xiaohongshu.com/explore/{note_id}"
                if xsec:
                    note_url += f"?xsec_token={xsec}&xsec_source=pc_user"

                ret = _process_one_note_api(
                    note_id, note_url, name, notes_dir() / "xiaohongshu" / name,
                    date_yymmdd, display_title=note.get("display_title")
                )
                if ret:
                    out.append(ret)
                    title, author, md_path, images_dir = ret[0], ret[1], ret[2], ret[3]
                    # 2026-08-15 fix #17: 顺序调换 - handoff OCR 必须在 publish 之前.
                    # 原因: append_single_to_hot 内部 _materialize_images() 会
                    # rmtree 整个 images_dir, publish 后再 handoff 会拿到空目录,
                    # 结果 ocr_inbox 里 0 张图 → VM OCR daemon 处理失败.
                    # 现在先 handoff (拷图到 VM), 再 publish.
                    if ocr_flag:
                        try:
                            from tools.handoff_vm_ocr import handoff_xhs_ocr_to_vm
                            publish_date = ""
                            try:
                                nid = note.get("note_id", "")
                                if len(nid) >= 8:
                                    import time
                                    ts = int(nid[:8], 16)
                                    publish_date = time.strftime("%Y-%m-%d", time.gmtime(ts))
                            except Exception:
                                pass
                            handoff_xhs_ocr_to_vm(
                                md_path=str(md_path),
                                images_dir=str(images_dir) if images_dir else "",
                                note_id=note.get("note_id") or "",
                                author=name,
                                title=title,
                                source_url=note_url,
                                publish_date=publish_date,
                            )
                        except Exception as e:
                            print(f"  ⚠️ [ocr-handoff] 异常: {e}")

                    # 2026-07-22: notes/ 中间目录已删，直接推 hot.md
                    try:
                        from common.publish_vault import append_single_to_hot
                        append_single_to_hot("xiaohongshu", md_path, images_dir=images_dir)
                    except Exception as e:
                        print(f"  ⚠️  hot.md 追加失败: {e}")

                # 频控: 每个 note 后 sleep
                if read_sleep > 0:
                    time.sleep(read_sleep)

    print(f"\n  OK xhs api done: {len(out)} 篇")
    return out


def crawl_user_posts_watchlist(date_yymmdd=None):
    """watchlist 监控别名."""
    return crawl_batch(date_yymmdd)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["clip", "monitor", "check"],
                    help="clip 单条, monitor watchlist, check 自检")
    ap.add_argument("--url")
    ap.add_argument("--date")
    args = ap.parse_args()
    if args.mode == "check":
        _check_xhs_cli_install()
        r = _run_xhs_json(["status"])
        print("✅ xhs-cli:", json.dumps(r, ensure_ascii=False, indent=2))
        _check_xhs_downloader_install()
        print(f"✅ xhs-downloader: {XHS_DOWNLOADER}")
        # opencli browser 检查
        out = _run_opencli(["doctor"], timeout=10)
        print(f"✅ opencli: {out or '未响应'}")
    elif args.mode == "monitor":
        for t in crawl_batch(args.date):
            print(t[0], "→", t[2])
    elif args.mode == "clip":
        if not args.url:
            print("需 --url")
            sys.exit(1)
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            print(crawl(args.url, d))



def _parse_note_time(note: dict) -> datetime:
    """从 xhs note dict 提取发布时间（naive datetime）。优先从 note_id[:8] hex 解析（最准）。"""
    # 方式1: note_id 前8位 hex = Unix timestamp（xhs ID 编码规则）
    nid = note.get("note_id", "")
    if len(nid) >= 8:
        try:
            ts = int(nid[:8], 16)
            return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
        except (ValueError, OSError):
            pass
    # 方式2: API 返回的 time 字段
    ts = (
        note.get("time") or
        note.get("created_at") or
        note.get("published_time") or
        note.get(" unix_time") or
        note.get("note_card", {}).get("time") or
        note.get("note_card", {}).get("created_at") or
        note.get("display_time")
    )
    if not ts:
        return datetime.max.replace(tzinfo=None)
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
        if isinstance(ts, str):
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%y%m%d%H%M%S"):
                try:
                    return datetime.strptime(ts[:19], fmt)
                except ValueError:
                    pass
    except Exception:
        pass
    return datetime.max.replace(tzinfo=None)

def _run_xhs_json(args, timeout=60):
    """调 `xhs <args> --json` 返回 dict.
       xhs read 可能先输出 WARNING/Captcha 行，再输出 JSON，
       所以从头开始找第一个 `{` 开头的行，从那里拼接到末尾作为完整 JSON。
    """
    cmd = [XHS_CLI] + list(args) + ["--json"]
    try:
        # macOS fork EAGAIN retry (close_fds=True 默认开启)
        r = _xhs_run_with_retry(cmd, capture_output=True, text=True, timeout=timeout, close_fds=True)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"xhs CLI 超时 (>{timeout}s): {' '.join(args)}")
    except FileNotFoundError:
        raise RuntimeError(f"xhs CLI 不存在: {XHS_CLI}")
    if r.returncode != 0:
        # 错误信息常在 stdout 的 JSON 里(如 ok:false error:Session expired),
        # 而非 stderr, 故两者都取, 方便定位(如登录过期/网络失败)
        detail = (r.stderr or r.stdout or "").strip()[:400]
        raise RuntimeError(f"xhs CLI 失败 rc={r.returncode}: {detail}")

    # 跳过 WARNING/INFO 等日志行，从第一个 `{` 开始拼接完整 JSON
    lines = r.stdout.strip().splitlines()
    json_start = -1
    for i, line in enumerate(lines):
        if line.strip().startswith("{"):
            json_start = i
            break
    if json_start == -1:
        raise RuntimeError(
            f"xhs CLI 输出中未找到 JSON 对象:\n"
            f"stdout({len(r.stdout)}b)={r.stdout[:300]}"
        )
    json_str = "\n".join(lines[json_start:])
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"xhs CLI JSON 解析失败: {e}\njson_str={json_str[:300]}")
    if not data.get("ok"):
        err = data.get("error") or data.get("message") or "unknown"
        raise RuntimeError(f"xhs CLI ok=false: {err}")
    return data


def _check_xhs_cli_install():
    if not Path(XHS_CLI).exists():
        raise RuntimeError(
            f"xiaohongshu-cli not installed: {XHS_CLI}\n"
            f"Install: uv tool install xiaohongshu-cli --with xhs\n"
            f"Login: {XHS_CLI} login --cookie-source chrome\n"
            f"Verify: {XHS_CLI} status"
        )


# ──────────── Helper functions ────────────
def _extract_user_id(profile_url: str) -> str | None:
    """Extract user_id from xhs profile URL."""
    m = re.search(r"/user/profile/([a-zA-Z0-9]+)", profile_url or "")
    return m.group(1) if m else None


def _pick_image_url(img: dict) -> str | None:
    """Pick best image URL from img dict."""
    for key in ["urlPre", "url_pre", "urlDefault", "url_default", "url"]:
        v = img.get(key)
        if v:
            return v
    for info in (img.get("info_list") or []):
        v = info.get("url")
        if v:
            return v
    return None


def _download_image(url: str, out_path: Path, timeout: int = 30) -> bool:
    """Download image URL to out_path. Returns True on success."""
    if not url:
        return False
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Referer": "https://www.xiaohongshu.com/",
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
        if len(data) < 200:
            return False
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)
        return True
    except Exception as e:
        print(f"    WARN img dl failed: {url[:60]} -> {e}")
        return False


def _yml_escape(s) -> str:
    """YAML-safe single-line value."""
    if s is None:
        return '""'
    s = str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f'"{s}"'


def _parse_count(v):
    """Parse count field to string."""
    if v is None:
        return "0"
    s = str(v).strip()
    return s if s else "0"


# ──────────── clip 入口 ────────────
def _check_xhs_downloader_install():
    if not HELPER.exists():
        raise RuntimeError(f"xhs-downloader helper missing: {HELPER}")
    if not PYTHON_VENV.exists():
        raise RuntimeError(f"xhs-downloader venv missing: {PYTHON_VENV}")


def _resolve_xhs_shortlink(url, timeout=25):
    """小红书分享链接默认是 xhslink.cn / xhslink.com 短链 (形如 xhslink.cn/o/<code>),
    直接交给 xhs-downloader 拿不到 note_id 会失败。此函数只做 GET 跟随 redirect,
    把短链解析成 xiaohongshu.com/discovery/item/<note_id>?... 真实 URL。

    注意: urllib 默认跟随 301/302 重定向, resp.geturl() 即最终 URL。
    解析失败时 (网络/风控) 原样返回, 不阻断, 交由下游 xhs-downloader 报错。
    """
    if "xhslink.cn" not in url and "xhslink.com" not in url:
        return url
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": UA, "Accept": "*/*"}, method="GET"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final = resp.geturl()
        if "xiaohongshu.com" in final:
            print(f"    🔗 xhslink 短链解析: {url[:40]}... → {final[:60]}...")
            return final
        print(f"    WARN xhslink 解析未落到 xiaohongshu.com: {final[:60]}, 用原 URL")
    except Exception as e:
        print(f"    WARN xhslink 解析失败, 用原 URL: {e}")
    return url


def crawl(url, tmp_dir, timeout=180):
    """clip / url entry: xhs-downloader wrapper. Returns (title, author, md_path, images_dir)."""
    # 2026-08-15 fix #18: xhslink 短链必须先解析成 xiaohongshu.com 真实 URL,
    # 否则 xhs-downloader 拿不到 note_id, 且 canonical_key 已把 xhslink.cn 路由到这里,
    # 但 short code 不是 note_id, 必须跟随 redirect 才能得到 <note_id>.
    url = _resolve_xhs_shortlink(url)
    res = _xhs_download_detail(url, tmp_dir, timeout)
    if not res.get("ok"):
        raise RuntimeError(f"xhs-downloader failed: {res.get('error', 'unknown')}")
    title = res["title"]
    author = res["author"]
    md_path = res["md_path"]
    images_dir = res.get("images_dir") or None
    downloads = res.get("downloads", 0)
    print(f"  OK: {title[:30]}... (author={author}, items={downloads})")
    return title, author, md_path, images_dir
