#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetchers/wechat.py — 微信公众号文章抓取 (API 方式, 参考 Mac ingest-wx/wechat.py)

requests + BeautifulSoup 内核抓取 mp.weixin.qq.com 文章 (js_content)。
删掉了 Mac 的 opencli 回退 (VM 无 opencli) — 正文为空直接抛异常。
"""
import os
import re
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://mp.weixin.qq.com/",
}


def crawl(url: str, tmp_dir: str, config: dict) -> tuple:
    """抓取微信公众号文章，返回 (title, author, md_path, images_dir)。"""
    proxy = config.get("vm", {}).get("proxy", "")
    # 微信文章不走代理 (国内直连) — Mac 内核也是直连
    headers = dict(DEFAULT_HEADERS)
    print(f"  📡 抓取: {url[:80]}")

    r = requests.get(url, headers=headers, timeout=30)
    r.encoding = r.apparent_encoding
    html = r.text
    if not html:
        raise RuntimeError("微信文章抓取失败 (空 HTML)")

    soup = BeautifulSoup(html, "lxml")
    title_tag = soup.find("h1", class_="rich_media_title") or soup.find("meta", property="og:title")
    title = title_tag.get_text(strip=True) if hasattr(title_tag, "get_text") else (
        title_tag.get("content", "") if title_tag else f"微信文章-{url[:30]}")

    author_tag = soup.find("span", class_="rich_media_meta_nickname")
    author = author_tag.get_text(strip=True) if author_tag else ""

    content_div = soup.find("div", id="js_content") or soup.find("div", class_="rich_media_content")
    content_html = str(content_div) if content_div else ""

    # 提取正文纯文本
    if content_html:
        content_soup = BeautifulSoup(content_html, "lxml")
        # 图片处理: 下载到 images/
        out_dir = Path(tmp_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        images_dir = out_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        image_mapping = _download_images(content_soup, url, images_dir)
        md = _html_to_md(content_soup, image_mapping)
    else:
        raise RuntimeError("微信文章 js_content 为空 (可能需要浏览器渲染, VM 无 opencli), 跳过")

    if not md or len(md.strip()) < 50:
        raise RuntimeError(f"微信文章正文过短 ({len(md) if md else 0} 字), 跳过")

    fm = [
        "---",
        f'title: "{_yaml_escape(title)}"',
        f'author: "{_yaml_escape(author or "")}"',
        f"source_url: {url}",
        "platform: wechat",
        f"created: {datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}",
        "---",
        "",
    ]
    md_path = out_dir / "note.md"
    md_path.write_text("\n".join(fm) + md, encoding="utf-8")
    print(f"  📰 标题: {title}")
    print(f"  💾 写入: {md_path.name} (正文 {len(md):,} 字)")
    return title, author, str(md_path), str(images_dir)


def _download_images(soup, base_url, images_dir):
    """下载微信文章图片, 返回 full_url -> local_path 映射"""
    import hashlib
    import urllib.request
    from urllib.parse import urljoin

    headers = {"User-Agent": DEFAULT_HEADERS["User-Agent"],
               "Referer": "https://mp.weixin.qq.com/"}
    image_mapping = {}
    for idx, img in enumerate(soup.find_all("img")):
        src = img.get("data-src") or img.get("src")
        if not src:
            continue
        full_url = urljoin(base_url, src)
        # wx 图片 CDN 格式
        ext = ".jpg"
        if "png" in full_url.lower():
            ext = ".png"
        elif "gif" in full_url.lower():
            ext = ".gif"
        local_name = f"img_{idx:03d}_{hashlib.md5(full_url.encode()).hexdigest()[:8]}{ext}"
        path = images_dir / local_name
        try:
            req = urllib.request.Request(full_url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
                if len(data) <= 5 * 1024 * 1024:
                    path.write_bytes(data)
                    image_mapping[full_url] = f"images/{local_name}"
        except Exception:
            pass
    print(f"  🖼️  图片: 下载 {len(image_mapping)} 张")
    return image_mapping


def _html_to_md(soup, image_mapping):
    """把微信 js_content 转 markdown"""
    # 简单转换: 段落到空行, 标题到 #, 图片到 ![]()
    parts = []
    for el in soup.descendants:
        if getattr(el, "name", None) == "img":
            src = el.get("data-src") or el.get("src")
            if src and src in image_mapping:
                parts.append(f"![]({image_mapping[src]})")
        elif getattr(el, "name", None) in ("h1", "h2", "h3", "h4", "h5", "h6"):
            t = el.get_text(strip=True)
            if t:
                lvl = int(el.name[1])
                parts.append(f"{'#' * lvl} {t}")
        elif getattr(el, "name", None) == "p":
            t = el.get_text(strip=True)
            if t:
                parts.append(t)
        elif getattr(el, "name", None) == "blockquote":
            t = el.get_text(strip=True)
            if t:
                parts.append(f"> {t}")
        elif getattr(el, "name", None) == "br":
            parts.append("")
    # 去重连续空行
    md = "\n\n".join([p for p in parts if p])
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md


def _yaml_escape(s):
    return s.replace('"', '\\"').replace("\n", " ").strip()