#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetchers/generic.py — 通用网页抓取 (API 方式, 参考 Mac tools/generic.py)

requests 下载 HTML + trafilatura 抽正文 + lxml 处理图片。
删掉了 Mac 的 opencli 兜底 (VM 无 opencli) — 反爬/正文过短时直接抛异常让主流程跳过或保留。
"""
import re
import urllib.parse
import urllib.request
from datetime import datetime
from html import unescape
from pathlib import Path

import requests
import trafilatura
from lxml import html as lxml_html

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}
# 知乎等站需要 Referer
EXTRA_REFERERS = {
    "zhihu.com": "https://www.zhihu.com/",
}


def crawl(url: str, tmp_dir: str, config: dict) -> tuple:
    """抓取通用网页，返回 (title, author, md_path, images_dir)。

    反爬站 (正文太短/403) 自动切 curl_cffi 浏览器 TLS 指纹重试 — 替代 Mac 的 opencli 兜底。
    """
    proxy = config.get("vm", {}).get("proxy", "")
    session = requests.Session()
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}

    headers = dict(DEFAULT_HEADERS)
    for host, ref in EXTRA_REFERERS.items():
        if host in url:
            headers["Referer"] = ref
            headers["Origin"] = ref.rstrip("/")
            break

    print(f"  📡 抓取: {url[:80]}")
    downloaded = None
    try:
        r = session.get(url, headers=headers, timeout=120, allow_redirects=True, verify=True)
        r.raise_for_status()
        if r.encoding and r.encoding.lower() not in ("iso-8859-1",):
            downloaded = r.content.decode(r.encoding, errors="replace")
        else:
            downloaded = r.content.decode("utf-8", errors="replace")
        print(f"  ✅ HTML 下载: {len(downloaded):,} bytes (requests)")
    except Exception as e:
        print(f"  ⚠️ requests 失败: {type(e).__name__}, 尝试 curl_cffi 浏览器指纹...")
        downloaded = _fetch_via_curl_cffi(url) or _fetch_via_urllib(url)
        if not downloaded:
            raise RuntimeError(f"HTTP 请求失败 ({type(e).__name__}): {str(e)[:120]}")

    meta = trafilatura.extract_metadata(downloaded)
    title = (meta.title if meta and meta.title else "").strip()
    raw_author = (meta.author if meta and meta.author else "").strip()
    author = _clean_author(raw_author)
    sitename = (meta.sitename if meta and meta.sitename else "").strip()
    date = (meta.date if meta and meta.date else "").strip()
    if not title:
        m = re.search(r"<title[^>]*>([^<]+)</title>", downloaded, re.I)
        if m:
            title = unescape(m.group(1).strip()).split("|")[0].split("-")[0].split("_")[0].strip()
    if not title:
        title = url[:50]
    print(f"  📰 标题: {title}")

    md_body = trafilatura.extract(
        downloaded, output_format="markdown", include_images=True,
        include_links=True, include_tables=True, include_formatting=True,
        favor_recall=True, with_metadata=False,
    )
    if not md_body or len(md_body) < 50:
        # 正文太短 → curl_cffi 浏览器指纹重抓 (替代 opencli)
        print(f"  ⚠️ 正文过短 ({len(md_body) if md_body else 0} 字), 尝试 curl_cffi 浏览器指纹...")
        rendered = _fetch_via_curl_cffi(url)
        if rendered:
            md_body = trafilatura.extract(
                rendered, output_format="markdown", include_images=True,
                include_links=True, include_tables=True, include_formatting=True,
                favor_recall=True, with_metadata=False,
            )
            if md_body and len(md_body) >= 50:
                downloaded = rendered
                print(f"  ✅ curl_cffi 浏览器指纹抓取成功: 正文 {len(md_body):,} 字")
        if not md_body or len(md_body) < 50:
            raise RuntimeError(f"正文太短 ({len(md_body) if md_body else 0} 字), trafilatura 抓不动")

    out_dir = Path(tmp_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    md_body, img_count = _download_images(md_body, downloaded, url, images_dir)

    md_content = _build_md(title, author, url, sitename, date, md_body, img_count)
    md_path = out_dir / "note.md"
    md_path.write_text(md_content, encoding="utf-8")
    print(f"  💾 写入: {md_path.name} (正文 {len(md_body):,} 字, 图片 {img_count})")
    return title, author, str(md_path), str(images_dir)


def _fetch_via_curl_cffi(url: str) -> str | None:
    """curl_cffi 浏览器 TLS 指纹抓取 (替代 opencli 兜底)"""
    try:
        from curl_cffi import requests as cr
        r = cr.get(url, impersonate="chrome", timeout=30)
        if r.status_code == 200 and r.text:
            return r.text
    except Exception as e:
        print(f"    [generic] curl_cffi 失败: {e}")
    return None


def _fetch_via_urllib(url: str) -> str | None:
    """urllib 抓取 (无代理场景兜底)"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_HEADERS["User-Agent"]})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


_IMG_MD_RE = re.compile(
    r"!\[([^\]]*)\]\((https?://[^)\s]+)\)|<img[^>]+src=[\"']?(https?://[^\"' >]+)", re.I)


def _download_images(md_body, html_text, base_url, images_dir):
    """下载 markdown/HTML 里的图片到本地"""
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
    if content_type:
        for ct_prefix, ext in ct_map.items():
            if ct_prefix in content_type:
                return ext
    return ".jpg"


def _build_md(title, author, url, sitename, date, body, img_count):
    """构建 md（含 frontmatter, 与 Mac generic 一致）"""
    parts = ["---"]
    parts.append(f'title: "{_yaml_escape(title)}"')
    if author:
        parts.append(f'author: "{_yaml_escape(author)}"')
    parts.append(f"source_url: {url}")
    parts.append("platform: generic-trafilatura")
    parts.append(f"created: {datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}")
    if sitename:
        parts.append(f'sitename: "{_yaml_escape(sitename)}"')
    if date:
        parts.append(f'date: "{date}"')
    parts.append(f"images: {img_count}")
    parts.append("---")
    parts.append("")
    parts.append(f"# {title}")
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