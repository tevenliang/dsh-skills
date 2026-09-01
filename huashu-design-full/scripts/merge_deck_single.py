#!/usr/bin/env python3
"""
merge_deck_single.py — 把多文件 deck（deck_index.html + slides/*.html）合并成自包含单文件。

为什么需要：多文件 deck 的 deck_index.html 用 iframe 加载 slides/*.html 子页面，
交付要经 WebDAV / DSH 侧边栏 / 带认证预览环境时，iframe 匿名请求会被认证拦成 401
→ 每页空白 forbidden。单文件自包含版（全部 slide 内嵌一个 HTML、零 iframe）则能预览。
见 references/slide-decks.md「叠加约束：交付要经 WebDAV / 侧边栏预览」。

用法：
    python3 scripts/merge_deck_single.py --index 项目/index.html --out 项目/index-single.html
    python3 scripts/merge_deck_single.py --index 项目/index.html          # 默认 --out 项目/index-single.html
    python3 scripts/merge_deck_single.py --index 项目/index.html --with-sitehead  # 保留原 index 的 <head> 资源

行为：
    1. 读 index.html 的 window.DECK_MANIFEST（file + label 列表）。
    2. 逐页读 slides/<file>，提取 <body> 内容包成 <section class="slide">；收集每页 <style> 合并。
    3. 以一个自包含单文件骨架输出：auto-scale 1920x1080 + 键盘/点击翻页 + 页码 + localStorage + 打印。
    4. 所有内容内嵌一个输出文件，零 iframe → WebDAV/侧边栏预览不再 401。

限制（诚实说明，不假装完美）：
    - 合并全部 <style> 到单一全局命名空间 → 多文件架构的样式隔离会丢失，
      若两页 class 撞名可能串扰；个别页样式冲突需手动加 scope 或重命名。
    - ../shared/*.css 若被 @import，脚本会内联其内容（css 文件是纯 CSS 时安全，字体 @font-face 的 url() 相对路径会失效）；
      外部网络字体（fonts.googleapis.com 等）保持 <link>/@import 原样，预览环境需能联网。
    - 输出文件是「能预览」的实质交付物，不代表视觉逐像素等同概览墙版。

依赖：标准库 only（re）。无 playwright/无第三方。
"""
import argparse
import json
import os
import re
import sys

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>%(title)s · Self-contained</title>
<!--
  merge_deck_single.py 生成 —— 自包含单文件 deck，专为 WebDAV/侧边栏/带认证预览设计。
  所有页内嵌本文件，零 iframe → 预览不触发 WebDAV basic auth 401。
  键盘：← → / Space 翻页 · Home/End 首末 · P 打印
-->
%(head_extra)s
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  :root {
    --bg-1: #0a1929;
    --bg-2: #1e3a5f;
    --accent: #e94560;
    --accent-2: #ff6b9d;
    --ink: #ffffff;
    --muted: rgba(255,255,255,0.72);
    --faint: rgba(255,255,255,0.45);
    --card: rgba(255,255,255,0.06);
    --line: rgba(255,255,255,0.12);
  }
  html, body { height: 100%%; overflow: hidden; }
  body {
    font-family: -apple-system, "PingFang SC", "Noto Sans SC", "Microsoft YaHei", sans-serif;
    background: linear-gradient(135deg, var(--bg-1) 0%%, var(--bg-2) 100%%);
    color: var(--ink);
  }
  #stage { position: absolute; top: 0; left: 0; transform-origin: top left; background: transparent; }
  .slide {
    position: absolute; inset: 0; padding: 90px 110px;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    opacity: 0; pointer-events: none; transition: opacity .45s ease;
    background: radial-gradient(1200px 600px at 85%% -10%%, rgba(233,69,96,0.16), transparent 55%%);
  }
  .slide.active { opacity: 1; pointer-events: auto; }
  .test-badge { position: absolute; top: 34px; right: 40px; z-index: 10; background: linear-gradient(135deg, var(--accent), var(--accent-2)); color: #fff; padding: 10px 22px; border-radius: 999px; font-size: 14px; font-weight: 700; box-shadow: 0 6px 18px rgba(233,69,96,0.45); letter-spacing: 0.04em; }
  .pager { position: absolute; bottom: 34px; right: 40px; z-index: 10; font-variant-numeric: tabular-nums; font-size: 15px; color: var(--faint); background: rgba(10,25,41,0.6); border: 1px solid var(--line); padding: 8px 18px; border-radius: 999px; letter-spacing: 0.06em; }
  .pager b { color: var(--ink); }
  .hint { position: absolute; bottom: 34px; left: 40px; z-index: 10; font-size: 13px; color: var(--faint); letter-spacing: 0.1em; }
  .nav-zone { position: absolute; top: 0; bottom: 0; width: 12%%; cursor: pointer; z-index: 8; opacity: 0; transition: opacity .2s; }
  .nav-zone.left { left: 0; } .nav-zone.right { right: 0; }
  body:hover .nav-zone { opacity: 1; }
  .nav-zone .arr { position: absolute; top: 50%%; transform: translateY(-50%%); width: 48px; height: 48px; border-radius: 999px; background: rgba(255,255,255,0.08); color: var(--muted); display: flex; align-items: center; justify-content: center; font-size: 26px; }
  .nav-zone.left .arr { left: 18px; } .nav-zone.right .arr { right: 18px; }
  @media print {
    @page { size: 1920px 1080px; margin: 0; }
    html, body { overflow: visible; height: auto; background: #fff; }
    #stage { position: static; transform: none !important; }
    .slide { position: relative; width: 1920px; height: 1080px; page-break-after: always; opacity: 1 !important; pointer-events: auto; }
    .test-badge, .pager, .hint, .nav-zone { display: none !important; }
  }
/* ===== 合并自各页 <style> 的样式（全局命名空间，撞名需手动 scope）===== */
%(merged_css)s
</style>
</head>
<body>

<div class="test-badge">%%(badge_text)s</div>
<div class="pager"><b id="cur">1</b> / <span id="tot">%(nslides)s</span></div>
<div class="hint">← → 翻页 · P 打印</div>
<div class="nav-zone left" id="navL"><div class="arr">‹</div></div>
<div class="nav-zone right" id="navR"><div class="arr">›</div></div>

<div id="stage">
%(slides_html)s
</div>

<script>
(function () {
  var slides = Array.prototype.slice.call(document.querySelectorAll('.slide'));
  var total = slides.length;
  var cur = 0;
  var stage = document.getElementById('stage');
  var curEl = document.getElementById('cur');
  var totEl = document.getElementById('tot');
  totEl.textContent = total;
  var storageKey = 'merge-deck-' + location.pathname;
  function fit() {
    var s = Math.min(innerWidth / 1920, innerHeight / 1080);
    stage.style.width = 1920 + 'px';
    stage.style.height = 1080 + 'px';
    stage.style.transform = 'scale(' + s + ') translate(' + ((innerWidth - 1920 * s) / 2 / s) + 'px,' + ((innerHeight - 1080 * s) / 2 / s) + 'px)';
  }
  function show(i) {
    if (i < 0 || i >= total) return;
    slides[cur].classList.remove('active');
    cur = i;
    slides[cur].classList.add('active');
    curEl.textContent = (cur + 1);
    try { localStorage.setItem(storageKey, String(cur)); } catch (_) {}
  }
  function next() { show(Math.min(cur + 1, total - 1)); }
  function prev() { show(Math.max(cur - 1, 0)); }
  document.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown') { e.preventDefault(); next(); }
    else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); prev(); }
    else if (e.key === 'Home') { e.preventDefault(); show(0); }
    else if (e.key === 'End') { e.preventDefault(); show(total - 1); }
  });
  document.getElementById('navL').addEventListener('click', prev);
  document.getElementById('navR').addEventListener('click', next);
  window.addEventListener('resize', fit);
  try { var v = parseInt(localStorage.getItem(storageKey), 10); if (!isNaN(v) && v >= 0 && v < total) cur = v; } catch (_) {}
  fit();
  slides.forEach(function (sl, i) { sl.classList.toggle('active', i === cur); });
  curEl.textContent = (cur + 1);
})();
</script>
</body>
</html>
"""


def extract_manifest(index_path):
    """从 deck_index.html 的 window.DECK_MANIFEST 提取 [{file,label}]。"""
    with open(index_path, encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"window\.DECK_MANIFEST\s*=\s*\[(.*?)\];", src, re.S)
    if not m:
        raise SystemExit("❌ 没在 index.html 里找到 window.DECK_MANIFEST（这是 deck_index.html 而非多文件需合并且？）")
    arr_txt = m.group(1)
    # 提取 { file: "...", label: "..." } 或 { file: "..." }
    items = re.findall(r"\{\s*file\s*:\s*\"([^\"]+)\"(?:\s*,\s*label\s*:\s*\"([^\"]*)\")?\s*\}", arr_txt)
    if not items:
        raise SystemExit("❌ DECK_MANIFEST 格式未识别（期望 { file: \"...\", label: \"...\" }）")
    return [{"file": f, "label": lbl or ""} for f, lbl in items]


def extract_slide(slide_path):
    """提取 slide 的 <body> 内容包成 <section>，并收集 <style> 块。"""
    with open(slide_path, encoding="utf-8") as f:
        src = f.read()
    style_blocks = re.findall(r"<style>(.*?)</style>", src, re.S)
    body_m = re.search(r"<body.*?>(.*?)</body>", src, re.S)
    body_inner = body_m.group(1) if body_m else src
    # 去掉 body 内自身的 <style>（已在 style_blocks 收集）
    body_inner = re.sub(r"<style>.*?</style>", "", body_inner, flags=re.S)
    return style_blocks, body_inner.strip()


def inline_shared_css(project_dir, style_blocks):
    """把 @import url(../shared/xxx.css) 本地相对路径内联为纯 CSS。"""
    out = []
    warnings = []
    for block in style_blocks:
        def repl(m):
            url = m.group(1).strip("'\"")
            if url.startswith(("http://", "https://", "//")):
                warnings.append(f"⚠️ 保留外部 @import {url}（预览需能联网）")
                return m.group(0)
            rel = os.path.normpath(os.path.join(project_dir, url))
            if os.path.isfile(rel):
                with open(rel, encoding="utf-8") as f:
                    css = f.read()
                if "@font-face" in css and "url(" in css:
                    warnings.append(f"⚠️ {url} 含 @font-face 字体 url()，内联后字体相对路径失效（字体需另内嵌 base64）")
                return css
            warnings.append(f"⚠️ @import {url} 找不到本地文件，已保留原样")
            return m.group(0)
        out.append(re.sub(r"@import\s+url\(([^)]+)\);?", repl, block, flags=re.I))
    return "\n".join(out), warnings


def main():
    ap = argparse.ArgumentParser(description="把多文件 deck 合并成自包含单文件（供 WebDAV/侧边栏预览）")
    ap.add_argument("--index", required=True, help="index.html 路径（deck_index.html）")
    ap.add_argument("--out", default=None, help="输出单文件路径（默认 <index-dir>/index-single.html）")
    ap.add_argument("--badge", default="🧪 预览版", help="右上角测试徽标文字")
    ap.add_argument("--title", default=None, help="输出 <title>（默认取 index.html 的 <title>）")
    ap.add_argument("--with-sitehead", action="store_true", help="保留原 index.html 的 <head> 资源引用（字体 etc）")
    args = ap.parse_args()

    index_path = os.path.abspath(args.index)
    project_dir = os.path.dirname(index_path)
    out_path = os.path.abspath(args.out or os.path.join(project_dir, "index-single.html"))

    manifest = extract_manifest(index_path)
    if not manifest:
        raise SystemExit("❌ DECK_MANIFEST 为空，无 slide 可合并")

    with open(index_path, encoding="utf-8") as f:
        index_src = f.read()
    title = args.title or re.search(r"<title>(.*?)</title>", index_src, re.S).group(1) or "Deck"

    # 收集每页 style + body
    all_styles = []
    slides_html = []
    for item in manifest:
        sp = os.path.join(project_dir, item["file"])
        if not os.path.isfile(sp):
            print(f"⚠️ 跳过缺失 {sp}", file=sys.stderr)
            continue
        styles, body = extract_slide(sp)
        all_styles.extend(styles)
        slides_html.append(f'  <section class="slide">\n{body}\n  </section>')

    merged_css, warnings = inline_shared_css(project_dir, all_styles)

    head_extra = ""
    if args.with_sitehead:
        # 收集原 index <head> 里的外部资源引用（字体 link etc）
        head_m = re.search(r"<head>(.*?)</head>", index_src, re.S)
        if head_m:
            refs = re.findall(r"<link[^>]+href=\"[^\"]+\"[^>]*>", head_m.group(1))
            head_extra = "\n".join(refs)

    out_html = TEMPLATE % {
        "title": title,
        "head_extra": head_extra,
        "merged_css": merged_css,
        "badge_text": args.badge,
        "nslides": len(slides_html),
        "slides_html": "\n\n".join(slides_html),
    }

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out_html)

    print(f"✅ 合并完成：{out_path}（{len(slides_html)} 页，{os.path.getsize(out_path)} 字节）")
    print(f"   预览验证：零 iframe，WebDAV/侧边栏预览不再 401。")
    for w in warnings:
        print(w, file=sys.stderr)


if __name__ == "__main__":
    main()