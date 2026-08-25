import os
_here = os.path.dirname(os.path.abspath(__file__))
while _here and not os.path.exists(os.path.join(_here, "_bootstrap.py")):
    _p = os.path.dirname(_here)
    if _p == _here:
        _here = None
        break
    _here = _p
if _here:
    if _here not in __import__('sys').path:
        __import__('sys').path.insert(0, _here)
import _bootstrap

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/wechat.py — 微信公众号文章抓取 (ominicrawl v1, 工具层)

返回统一契约: (title, author, md_path, images_dir)

抓取策略（2026-07-22 加 opencli 回退）:
  1. 内核 (requests + BeautifulSoup, 不依赖浏览器) 先抓
     - 优点: 快, 无浏览器开销
     - 缺点: JS 渲染内容拿不到 (正文为空)
  2. 内核生成 md 正文为空时 → opencli 回退
     - 用用户 Chrome 副 profile 的登录态 (Cookie) 渲染页面
     - 适合: 需要登录才能访问全文的微信文章
"""
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

KERNEL = Path(__file__).parent / "_wechat_kernel_main.py"
PY = sys.executable


def _body_len(md_path):
    """返回 md 文件正文（非 frontmatter + metadata）字符数。"""
    try:
        text = open(md_path, encoding="utf-8").read()
    except Exception:
        return 0
    # 跳过 frontmatter + metadata block (到第一个 --- 分隔线之后)
    if text.startswith("---\n"):
        idx = text.find("\n---\n", 4)
        if idx >= 0:
            text = text[idx + 5:]
    # 找第一个 Markdown 标题 (正文开始)
    idx = text.find("\n# ")
    if idx >= 0:
        text = text[idx + 3:]
    # 去掉末尾 metadata 行
    lines = text.splitlines()
    body_lines = []
    for ln in lines:
        if ln.startswith("**") and "**: " in ln:
            continue  # 跳过 metadata 行
        body_lines.append(ln)
    body = "\n".join(body_lines).strip()
    return len(body)


def _render_with_opencli(url, tmp_dir):
    """用 opencli 浏览器渲染抓取微信文章（回退路径）。"""
    sys.path.insert(0, str(Path(__file__).parent))
    from opencli_bridge import fetch_rendered

    print(f"  [opencli 回退] 尝试浏览器渲染: {url[:60]}")
    md_text, html = fetch_rendered(url, wait_secs=8)
    if not md_text or len(md_text.strip()) < 50:
        raise RuntimeError(f"opencli 回退也失败: markdown 内容 < 50 字符")

    # 解析 opencli 提取出来的标题
    title = None
    for line in md_text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            title = line[2:].strip()
            break
    if not title:
        title = md_text.split("\n")[0][:50] if md_text else "微信文章"

    # 写 md 文件
    md_path = os.path.join(tmp_dir, "wechat-opencli.md")
    frontmatter = (
        f"# {title}\n\n"
        f"**原文链接**: {url}\n"
        f"**抓取时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        "---\n\n"
    )
    open(md_path, "w", encoding="utf-8").write(frontmatter + md_text)
    print(f"  [opencli] 生成: {md_path}")
    return title, md_path


def crawl(url, tmp_dir, timeout=90):
    """抓微信文章到 tmp_dir。返回 (title, author, md_path, images_dir)。"""
    os.makedirs(tmp_dir, exist_ok=True)

    # ── 1. 内核先抓 ──
    if KERNEL.exists():
        r = subprocess.run(
            [PY, str(KERNEL), url, tmp_dir],
            capture_output=True, text=True, timeout=timeout,
        )
        kernel_ok = r.returncode == 0
    else:
        kernel_ok = False

    md_files = [f for f in os.listdir(tmp_dir) if f.endswith(".md")]
    if not md_files and not kernel_ok:
        raise RuntimeError(f"wechat 内核不存在且无 md 文件: {KERNEL}")

    # 解析内核输出
    title, author = None, None
    if kernel_ok:
        for line in r.stdout.splitlines():
            if line.startswith("📰 标题："):
                title = line.split("：", 1)[1].strip()
            elif line.startswith("✍️ 作者："):
                author = line.split("：", 1)[1].strip()

    md_path = None
    if md_files:
        md_path = os.path.join(tmp_dir, md_files[0])

    # ── 2. 检查正文是否为空 → opencli 回退 ──
    if md_path and os.path.exists(md_path):
        body_len = _body_len(md_path)
        # 正文 < 30 字符视为无效（内核抓不到 JS 渲染内容）
        if body_len < 30:
            print(f"  ⚠️ 内核正文为空 (body={body_len}), 触发 opencli 回退")
            try:
                title2, md_path2 = _render_with_opencli(url, tmp_dir)
                if title2:
                    title = title2
                md_path = md_path2
            except Exception as e:
                print(f"  ⚠️ opencli 回退也失败: {e}, 保留内核结果")
                if not title:
                    title = os.path.splitext(md_files[0])[0] if md_files else "微信文章"
        else:
            # 内核结果有效
            if not title:
                title = os.path.splitext(md_files[0])[0] if md_files else "微信文章"
    else:
        # 无 md 文件，尝试 opencli
        title, md_path = _render_with_opencli(url, tmp_dir)

    if not md_path or not os.path.exists(md_path):
        raise RuntimeError("wechat: 未能生成 md 文件（内核+opencli 均失败）")

    images_dir = os.path.join(tmp_dir, "images")
    return title, author, md_path, images_dir


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python wechat.py <URL> <tmp_dir>")
        sys.exit(1)
    t, a, m, i = crawl(sys.argv[1], sys.argv[2])
    print(f"title={t}\nauthor={a}\nmd={m}\nimages_dir={i}")
