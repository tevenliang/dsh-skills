#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clipboard.py — vault/01_my_notes/clip.md 单文件剪藏队列管理器 (照搬 Mac ingest-wx/clipboard.py)

入口: vault/01_my_notes/clip.md
  一个文件就是一个队列
  - frontmatter 可选,正文每行一个 URL
  - # 开头的行作为注释被忽略
  - 抓取成功后 remove_url_from_note() 删去对应行 (按 canonical_key 匹配)

出口: vault/00_inbox/MMDD-<safe-title>.md (由 fetchers 负责)
"""
import os
import re
from pathlib import Path


def _vault_base() -> Path:
    """vault 解析: 优先 env VAULT, 否则默认 VM 路径"""
    env = os.environ.get("VAULT", "")
    if env and Path(env).exists():
        return Path(env)
    return Path("/home/ubuntu/webdav/steven_vault")


CLIP_FILE = _vault_base() / "01_my_notes" / "clip.md"


# ── URL 抽取 (与原 AppleScript 版本完全相同,接口稳定) ──

def extract_urls(text):
    """从正文提取所有 URL, 自动剥离抖音/B站「复制链接」分享噪音。
    干净链接与噪音(分享尾巴/描述文字)以空格分隔。

    2026-07-21 修复: 两条 URL 粘连时在 https?:// 之前插入换行, \\S+ 自然截断。
    """
    raw = re.sub(r'(https?://)', r'\n\1', text)
    urls = re.findall(r'https?://\S+', raw)
    out, seen = [], set()
    for u in urls:
        u = re.sub(r'[)）】」』>，。；,;:\s]+$', '', u)
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def canonical_key(url):
    """返回 (平台, ID) 稳定 key, 用于跨"笔记原始URL(带query)"与"干净URL"匹配。"""
    u = url.lower()
    if "bilibili.com" in u or "b23.tv" in u:
        m = re.search(r'(BV[0-9A-Za-z]+)', url)
        return ("bilibili", m.group(1) if m else url)
    if "douyin.com" in u or "iesdouyin.com" in u:
        m = re.search(r'/video/(\d+)', url)
        return ("douyin", m.group(1) if m else url)
    if "mp.weixin.qq.com" in u:
        m = re.search(r'/s/([\w\-]+)', url)
        return ("wechat", m.group(1) if m else url)
    if "xiaohongshu.com" in u or "xhslink.com" in u or "xhslink.cn" in u:
        m = re.search(r'/(note|explore|discovery/item)/([0-9A-Za-z]+)', url)
        return ("xiaohongshu", m.group(2) if m else url)
    return ("generic", url)


# ── 队列读写 ──

def _ensure_clip_file():
    """确保 clip.md 存在。首次调用时创建 (含 frontmatter 模板)。"""
    if not CLIP_FILE.exists():
        CLIP_FILE.parent.mkdir(parents=True, exist_ok=True)
        CLIP_FILE.write_text(
            "---\n"
            "type: clip_inbox\n"
            "note: 复制链接后粘贴到下方，每行一个 URL；处理成功后行自动删除\n"
            "---\n\n"
            "# 网页剪藏队列（clip 入口）\n"
            "# 粘贴到下方即可:\n\n",
            encoding="utf-8",
        )
    return CLIP_FILE


def _strip_frontmatter(text: str) -> str:
    """去掉 md 的 YAML frontmatter 块, 返回正文。"""
    if not text.startswith("---\n"):
        return text
    m = re.search(r'\n---\s*\n', text[4:])
    if m:
        return text[4 + m.end():]
    return text


def read_clip_text():
    """读取 clip.md 正文 (去 frontmatter) 返回字符串,供 extract_urls 抽链接。"""
    _ensure_clip_file()
    try:
        content = CLIP_FILE.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return _strip_frontmatter(content)


def remove_url_from_note(target_url, dry_run=False):
    """从 clip.md 中删除包含 target_url 的那一行 (按 canonical_key 匹配)。"""
    tkey = canonical_key(target_url)

    if not CLIP_FILE.exists():
        return None

    try:
        content = CLIP_FILE.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    lines = content.splitlines(keepends=True)
    new_lines = []
    file_changed = False
    for ln in lines:
        stripped = ln.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(ln)
            continue
        line_urls = extract_urls(stripped)
        hit = any(canonical_key(u) == tkey for u in line_urls)
        if hit:
            file_changed = True
            continue
        new_lines.append(ln)

    if not file_changed:
        return None

    if dry_run:
        print(f"  [dry-run] 会删除 {CLIP_FILE.name} 中匹配行")
        return True

    new_content = "".join(new_lines)
    tmp = CLIP_FILE.with_suffix(".md.tmp")
    tmp.write_text(new_content, encoding="utf-8")
    os.replace(tmp, CLIP_FILE)
    print(f"  🗑️  已删 URL 行 from {CLIP_FILE.name}")
    return True


if __name__ == "__main__":
    print(f"=== clip file: {CLIP_FILE} ===")
    t = read_clip_text()
    print("=== 正文 ===")
    print(t)
    print("\n=== 提取到的 URL ===")
    for u in extract_urls(t):
        print(" ", canonical_key(u), u)