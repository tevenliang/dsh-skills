#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/generic.py — 通用网页抓取 (ominicrawl v1, 工具层)

调 trafilatura 抽正文 + metadata; 反爬站(知乎/微博等)自动走 opencli_bridge
真实 Chrome 兜底。统一收口到 common.opencli_bridge (静默拉起副profile + 关窗)。

返回统一契约: (title, author, md_path, images_dir)
"""
import json
import os
import re
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path

import requests
import trafilatura
from lxml import html as lxml_html

from common.opencli_bridge import fetch_rendered

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


def _headers_for(url):
    h = dict(DEFAULT_HEADERS)
    if "zhihu.com" in url or "zhuanlan.zhihu.com" in url:
        h["Referer"] = "https://www.zhihu.com/"
        h["Origin"] = "https://www.zhihu.com"
    return h


def crawl(url, tmp_dir, timeout=120):
    """抓取通用网页, 返回 (title, author, md_path, images_dir)。"""
    output_dir = Path(tmp_dir)
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    print(f"  📡 抓取: {url}")

    try:
        r = requests.get(
            url, headers=_headers_for(url), timeout=timeout,
            allow_redirects=True, verify=True,
        )
        r.raise_for_status()
        if r.encoding and r.encoding.lower() not in ("iso-8859-1",):
            downloaded = r.content.decode(r.encoding, errors="replace")
        else:
            downloaded = r.content.decode("utf-8", errors="replace")
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else 0
        if code in (401, 403, 429):
            print(f"  ⚠️ HTTP {code}, 疑似反爬, 改用 opencli 真实浏览器兜底...")
            return _crawl_via_opencli(url, tmp_dir)
        if code == 404:
            raise RuntimeError(f"HTTP 404 Not Found ({url[:80]})")
        raise RuntimeError(f"HTTP 请求失败 ({code} {type(e).__name__}): {str(e)[:120]}")
    except requests.RequestException as e:
        raise RuntimeError(f"HTTP 请求失败 ({type(e).__name__}): {str(e)[:120]}")

    if not downloaded.strip():
        raise RuntimeError(f"下载内容为空 (可能 404/SPA): {url}")
    print(f"  ✅ HTML 下载: {len(downloaded):,} bytes")

    meta = trafilatura.extract_metadata(downloaded)
    title = (meta.title if meta and meta.title else "").strip()
    raw_author = (meta.author if meta and meta.author else "").strip()
    author = _clean_author(raw_author)
    date = (meta.date if meta and meta.date else "").strip()
    sitename = (meta.sitename if meta and meta.sitename else "").strip()
    if not title:
        m = re.search(r"<title[^>]*>([^<]+)</title>", downloaded, re.I)
        if m:
            title = unescape(m.group(1).strip()).split("|")[0].split("-")[0].strip()
    if not title:
        title = url[:50]
    print(f"  📰 标题: {title}")
    if author:
        print(f"  ✍️  作者: {author}")

    md_body = trafilatura.extract(
        downloaded, output_format="markdown", include_images=True,
        include_links=True, include_tables=True, include_formatting=True,
        favor_precision=True, with_metadata=False,
    )
    if not md_body or len(md_body) < 50:
        print("  ⚠️ 正文过短, 疑似反爬挑战页/SPA, 尝试 opencli 真实浏览器兜底...")
        try:
            return _crawl_via_opencli(url, tmp_dir)
        except Exception as e2:
            raise RuntimeError(
                f"正文太短 ({len(md_body) if md_body else 0} 字), trafilatura 抓不动; "
                f"opencli 兜底也失败: {e2}"
            )
    print(f"  📝 正文: {len(md_body):,} 字")

    md_body, img_count = _download_images(md_body, downloaded, url, images_dir)
    print(f"  🖼️  图片: 下载 {img_count} 张")

    md_content = _build_md(title, author, url, sitename, date, md_body, img_count)
    md_path = output_dir / "note.md"
    md_path.write_text(md_content, encoding="utf-8")
    print(f"  💾 写入: {md_path}")
    return title, author, str(md_path), str(images_dir)


# ── opencli 真实 Chrome 桥接兜底 (反爬站点) ──
def _crawl_via_opencli(url, tmp_dir):
    output_dir = Path(tmp_dir)
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    print(f"  🌐 [opencli] 真实 Chrome 桥接抓取: {url}")
    content, html = fetch_rendered(url, wait_secs=5)
    if not content.strip():
        raise RuntimeError("opencli 抽取内容为空 (可能需登录或页面未渲染)")
    print(f"  📝 [opencli] 正文: {len(content):,} 字")

    title, author, date = _parse_opencli_header(content, url)

    img_locals = []
    if html:
        img_locals = _download_images_opencli(html, url, images_dir)
        if img_locals:
            content += "\n\n## 图集\n"
            for fn in img_locals:
                content += f"![](images/{fn})\n"

    sitename = "知乎专栏" if "zhihu" in url else ""
    md_content = _build_md(title, author, url, sitename, date, content, len(img_locals))
    md_path = output_dir / "note.md"
    md_path.write_text(md_content, encoding="utf-8")
    print(f"  💾 写入: {md_path}")
    return title, author, str(md_path), str(images_dir)


def _parse_opencli_header(content, url):
    title, author, date = "", "", ""
    for ln in content.splitlines():
        s = ln.strip()
        if not title and s.startswith("# "):
            title = s[2:].strip()
        elif not author and s.startswith("**") and "**" in s[2:]:
            m = re.match(r"\*\*[^*]+\*\*\s*(.+)", s)
            if m:
                author = m.group(1).strip()
        elif not date and s.startswith("_") and s.endswith("_"):
            inner = s[1:-1].strip()
            if re.search(r"\d{4}\s*年", inner):
                date = inner
        if title and author and date:
            break
    if not title:
        title = url[:50]
    return title, author, date


def _download_images_opencli(html_text, base_url, images_dir):
    candidates = []
    for m in re.finditer(
        r'<img\b[^>]*?(?:\bdata-actualsrc|\bsrc|\bdata-src)\s*=\s*["\']([^"\']+)["\']',
        html_text, re.I):
        u = m.group(1).strip()
        if u.startswith("data:image"):
            continue
        if u.startswith("//"):
            u = "https:" + u
        elif u.startswith("/"):
            parsed = urllib.parse.urlparse(base_url)
            u = f"{parsed.scheme}://{parsed.netloc}{u}"
        elif not u.startswith("http"):
            u = urllib.parse.urljoin(base_url, u)
        candidates.append(u)

    referer = urllib.parse.urlparse(base_url)
    referer = f"{referer.scheme}://{referer.netloc}/"
    headers = {"User-Agent": DEFAULT_HEADERS["User-Agent"], "Referer": referer}

    locs, seen = [], set()
    for u in candidates:
        if u in seen:
            continue
        seen.add(u)
        try:
            req = urllib.request.Request(u, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
                if len(data) > 5 * 1024 * 1024:
                    continue
                ct = resp.headers.get("Content-Type", "")
                ext = _ext_from_url_or_ct(u, ct)
                local_name = f"img_{len(locs):03d}{ext}"
                (images_dir / local_name).write_bytes(data)
                locs.append(local_name)
        except Exception:
            pass
        if len(locs) >= 30:
            break
    if locs:
        print(f"  🖼️  [opencli] 图片: 下载 {len(locs)} 张")
    return locs


_IMG_MD_RE = re.compile(
    r"!\[([^\]]*)\]\((https?://[^)\s]+)\)|<img[^>]+src=[\"']?(https?://[^\"' >]+)", re.I)


def _download_images(md_body, html_text, base_url, images_dir):
    parsed_base = urllib.parse.urlparse(base_url)
    base_origin = f"{parsed_base.scheme}://{parsed_base.netloc}"
    img_urls = set()
    for m in _IMG_MD_RE.finditer(md_body):
        u = m.group(2) or m.group(3)
        if u:
            img_urls.add(u)
    try:
        tree = lxml_html.fromstring(html_text)
        for img in tree.xpath("//img[@src]"):
            src = img.get("src", "").strip()
            if src:
                if src.startswith("//"):
                    src = "https:" + src
                elif src.startswith("/"):
                    src = base_origin + src
                elif not src.startswith("http"):
                    src = urllib.parse.urljoin(base_url, src)
                img_urls.add(src)
    except Exception:
        pass

    headers = {"User-Agent": DEFAULT_HEADERS["User-Agent"]}
    url_to_local = {}
    for i, img_url in enumerate(sorted(img_urls)):
        try:
            req = urllib.request.Request(img_url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
                if len(data) > 5 * 1024 * 1024:
                    continue
                ct = resp.headers.get("Content-Type", "")
                ext = _ext_from_url_or_ct(img_url, ct)
                local_name = f"img_{i:03d}{ext}"
                (images_dir / local_name).write_bytes(data)
                url_to_local[img_url] = local_name
        except Exception:
            pass

    def rewrite(m):
        url = m.group(2) or m.group(3)
        if url in url_to_local:
            return f"![{m.group(1) or ''}](images/{url_to_local[url]})"
        return m.group(0)

    new_md = _IMG_MD_RE.sub(rewrite, md_body)
    referenced = set()
    for m in _IMG_MD_RE.finditer(md_body):
        url = m.group(2) or m.group(3)
        if url in url_to_local:
            referenced.add(url_to_local[url])
    unused = [(u, local) for u, local in url_to_local.items() if local not in referenced]
    if unused:
        new_md += "\n\n## 图集\n"
        for _url, local_name in sorted(unused, key=lambda x: x[1]):
            new_md += f"![](images/{local_name})\n"
    return new_md, len(url_to_local)


def _ext_from_url_or_ct(url, content_type):
    path = urllib.parse.urlparse(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    ct_map = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
              "image/webp": ".webp", "image/svg+xml": ".svg"}
    for ct_prefix, ext in ct_map.items():
        if ct in ct_prefix:
            return ext
    return ".jpg"


def _build_md(title, author, url, sitename, date, body, img_count):
    parts = ["---"]
    parts.append(f'title: "{_yaml_escape(title)}"')
    if author:
        parts.append(f'author: "{_yaml_escape(author)}"')
    parts.append(f'source: {url}')
    parts.append('platform: generic-trafilatura')
    if sitename:
        parts.append(f'sitename: "{_yaml_escape(sitename)}"')
    if date:
        parts.append(f'date: "{date}"')
    parts.append(f"images: {img_count}")
    parts.append("---")
    parts.append("")
    parts.append(f"## {title}")
    parts.append("")
    parts.append(body)
    return "\n".join(parts)


def _yaml_escape(s):
    return s.replace('"', '\\"').replace("\n", " ").strip()


def _clean_author(raw):
    if not raw:
        return ""
    candidates = re.split(r"[,，;；|/／]+", raw)
    noise = ("规范控制", "ISNI", "BNF", "FAST", "Bibliothèque", "nationale", "de France",
             "United States", "Data", "Germany", "Israel", "Japan", "Czech", "Latvia",
             "Spain", "France", "其他", "学术", "AAT", "Nara", "Idref")
    for c in candidates:
        c = c.strip()
        if not c or len(c) > 50:
            continue
        if any(n in c for n in noise):
            continue
        return c
    return ""
