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

#!/usr/bin/env python3
"""
微信公众号文章爬虫 - 保留图片尺寸和原文格式
用法: python main.py <文章URL> [输出目录]
"""
import sys, os, re
from datetime import datetime
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import requests
import hashlib

DEFAULT_OUTPUT_DIR = os.path.expanduser('~/.agents/skills/crawl/ingest-wx/files')


def fetch_article(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept-Language': 'zh-CN,zh;q=0.9',
    }
    r = requests.get(url, headers=headers, timeout=15)
    r.encoding = r.apparent_encoding
    return r.text


def extract_content(html, url):
    soup = BeautifulSoup(html, 'lxml')
    # 标题
    title_tag = soup.find('h1', class_='rich_media_title') or soup.find('meta', property='og:title')
    title = title_tag.get_text(strip=True) if hasattr(title_tag, 'get_text') else (title_tag.get('content', '') if title_tag else f'微信文章-{url}')
    # 作者
    author_tag = soup.find('span', class_='rich_media_meta_nickname')
    author = author_tag.get_text(strip=True) if author_tag else ''
    # 正文
    content_div = soup.find('div', id='js_content') or soup.find('div', class_='rich_media_content')
    content_html = str(content_div) if content_div else ''
    return {'title': title, 'author': author, 'content_html': content_html, 'raw_html': html}


def get_filename(url, idx):
    ext = os.path.splitext(urlparse(url).path)[1] or '.jpg'
    if len(ext) > 5:
        ext = '.jpg'
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    return f'img_{idx:03d}_{url_hash}{ext}'


def download_img(url, path):
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://mp.weixin.qq.com/'}
    try:
        r = requests.get(url, headers=headers, timeout=10, stream=True)
        r.raise_for_status()
        with open(path, 'wb') as f:
            for c in r.iter_content(8192):
                f.write(c)
        return True
    except Exception as e:
        print(f'⚠️ 下载失败：{url} - {e}')
        return False


def extract_images(html, base_url):
    soup = BeautifulSoup(html, 'lxml')
    imgs = []
    for img in soup.find_all('img'):
        src = img.get('data-src') or img.get('src')
        if src:
            imgs.append((urljoin(base_url, src), img))
    return imgs


def process_element(el, image_info):
    """递归将 HTML 元素转为 Markdown，保留图片尺寸"""
    if isinstance(el, str):
        t = el.strip()
        return t if t else None

    if el.name == 'img':
        src = el.get('data-src') or el.get('src')
        if not src:
            return None
        local_path, w, h = None, None, None
        alt = el.get('alt', '')
        for full_url, (lp, pw, ph) in image_info.items():
            if src == full_url or src in full_url:
                local_path, w, h = lp, pw, ph
                break
        if not local_path:
            return None
        if w:
            if h:
                return f'<img src="{local_path}" width="{w}" height="{h}" alt="{alt}">'
            return f'<img src="{local_path}" width="{w}" alt="{alt}">'
        return f'![{alt}]({local_path})'

    if el.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
        lvl = int(el.name[1])
        t = el.get_text(strip=True)
        return f"{'#' * lvl} {t}" if t else None

    if el.name == 'p':
        parts = [process_element(c, image_info) for c in el.children]
        parts = [p for p in parts if p]
        return ' '.join(parts) if parts else None

    if el.name == 'blockquote':
        t = el.get_text(strip=True)
        return f'> {t}' if t else None

    if el.name in ['ul', 'ol']:
        items = []
        for li in el.find_all('li', recursive=False):
            t = li.get_text(strip=True)
            if t:
                items.append(f'- {t}' if el.name == 'ul' else f'1. {t}')
        return '\n'.join(items) if items else None

    if el.name == 'br':
        return '\n'

    if el.name == 'section':
        parts = [process_element(c, image_info) for c in el.children]
        parts = [p for p in parts if p]
        return '\n\n'.join(parts) if parts else None

    parts = [process_element(c, image_info) for c in el.children]
    parts = [p for p in parts if p]
    if el.name in ['div', 'p', 'section', 'blockquote']:
        return '\n\n'.join(parts) if parts else None
    return ' '.join(parts) if parts else None


def html_to_md(content_html, url, image_mapping):
    if not content_html:
        return ''
    soup = BeautifulSoup(content_html, 'lxml')

    # 建立 image_info: full_url -> (local_path, width, height)
    image_info = {}
    for img in soup.find_all('img'):
        src = img.get('data-src') or img.get('src')
        if not src:
            continue
        full_url = urljoin(url, src)
        if full_url not in image_mapping:
            continue
        lp = image_mapping[full_url]

        # 从 style 解析尺寸
        style = img.get('style', '')
        w, h = None, None
        if 'width' in style:
            wm = re.search(r'width\s*:\s*(\d+)px', style)
            hm = re.search(r'height\s*:\s*(\d+)px', style)
            if wm:
                w = wm.group(1)
            if hm:
                h = hm.group(1)

        # 从 data-w + data-ratio 计算
        if not w:
            dw = img.get('data-w')
            if dw:
                w = dw
                ratio = img.get('data-ratio')
                if ratio and not h:
                    try:
                        h = str(int(float(dw) * float(ratio)))
                    except:
                        pass

        image_info[full_url] = (lp, w, h)

    # 手动转换
    md_parts = []
    for el in soup.children:
        r = process_element(el, image_info)
        if r:
            md_parts.append(r)

    md = '\n\n'.join(md_parts)
    md = re.sub(r'\n{3,}', '\n\n', md)
    return md


def main():
    if len(sys.argv) < 2:
        print('用法: python main.py <文章URL> [输出目录]')
        sys.exit(1)

    article_url = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)

    print(f'📥 抓取文章：{article_url}')
    html = fetch_article(article_url)
    if not html:
        print('❌ 抓取失败')
        sys.exit(1)
    print('✅ 抓取成功')

    article = extract_content(html, article_url)
    print(f'📰 标题：{article["title"]}')
    if article['author']:
        print(f'✍️ 作者：{article["author"]}')

    print('🖼️  提取图片...')
    imgs = extract_images(article['raw_html'], article_url)
    print(f'📸 找到 {len(imgs)} 张图片')

    images_dir = os.path.join(output_dir, 'images')
    os.makedirs(images_dir, exist_ok=True)
    image_mapping = {}
    for idx, (img_url, img_tag) in enumerate(imgs, 1):
        fn = get_filename(img_url, idx)
        path = os.path.join(images_dir, fn)
        if download_img(img_url, path):
            image_mapping[img_url] = f'images/{fn}'

    print(f'✅ 下载 {len(image_mapping)}/{len(imgs)} 张图片')

    print('📝 转换 Markdown...')
    md = html_to_md(article['content_html'], article_url, image_mapping)

    safe_title = article['title'][:50].replace('/', '_').replace('\\', '_')
    safe_title = ''.join(c for c in safe_title if c.isalnum() or c in ' -_').strip()
    if not safe_title:
        safe_title = 'wechat-article'

    frontmatter = [
        f"# {article['title']}",
        "",
        f"**作者**: {article['author']}",
        f"**原文链接**: {article_url}",
        f"**抓取时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        "",
    ]
    final = '\n'.join(frontmatter) + md

    md_path = os.path.join(output_dir, f'{safe_title}.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(final)

    print(f'✅ 保存成功：{md_path}')
    print(f'📁 图片目录：{images_dir}/')


if __name__ == '__main__':
    main()