#!/usr/bin/env python3
"""
clipboard.py — Apple 备忘录「网页剪藏」管理器

职责:
  1. read_clip_text()      读取笔记纯文本正文
  2. extract_urls(text)    从正文提取所有 URL (自动拆分粘连的连续链接)
  3. canonical_key(url)    返回用于匹配/去重的稳定 key (平台|ID)
  4. remove_url_from_note(target_url, dry_run=False)
                          从笔记中删除"包含 target_url 的那条链接"并写回

删除策略: 笔记实际是单行段落(URL 以空格分隔), 因此用"子串移除"而非按行删。
          匹配依据 canonical_key, 避免 B站长 query 参数干扰。
"""
import re
import subprocess

NOTE_KW = "网页剪藏"   # 用于 `name contains` 定位笔记 (笔记无独立标题行, name 被派生成整段内容)


def _run_osascript(script):
    res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"osascript 失败({res.returncode}): {res.stderr.strip()}")
    return res.stdout


def read_clip_text():
    """读取「网页剪藏」笔记纯文本正文 (单行段落, URL 以空格分隔)"""
    s = f'tell application "Notes" to get plaintext of (first note whose name contains "{NOTE_KW}")'
    return _run_osascript(s).strip()


def extract_urls(text):
    """从正文提取所有 URL, 自动拆分粘连的连续链接 (如 ahttps://b)。

    返回去重后的 URL 列表 (保持出现顺序)。
    """
    # 在每个 https?:// 之前切分, 自然拆开粘连链接
    parts = re.split(r'(?=https?://)', text)
    urls = []
    seen = set()
    for p in parts:
        p = p.strip()
        if not p.lower().startswith("http"):
            continue
        # 去掉结尾可能粘连的标点/空白
        p = re.sub(r'[)\]}>"\'，。；,;]+$', '', p)
        if p and p not in seen:
            seen.add(p)
            urls.append(p)
    return urls


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
    if "xiaohongshu.com" in u or "xhslink.com" in u:
        m = re.search(r'/(note|explore|discovery/item)/([0-9A-Za-z]+)', url)
        return ("xiaohongshu", m.group(2) if m else url)
    return ("generic", url)


def _esc_html(s):
    """转义 AppleScript 字符串中的引号与反斜杠 (写入 body 用)"""
    return s.replace('\\', '\\\\').replace('"', '\\"')


def remove_url_from_note(target_url, dry_run=False):
    """从笔记中删除包含 target_url 的那条链接。

    返回:
      None  -> 笔记中未找到该链接 (无需操作)
      True  -> 已删除 (或 dry_run 下会删除)
    副作用: 非 dry_run 时写回笔记 body (保留「网页剪藏 网页剪藏列表:」表头)
    """
    tkey = canonical_key(target_url)
    text = read_clip_text()
    # 拆出表头(首个 http 之前) 与 URL 列表
    m = re.search(r'https?://', text)
    header = text[:m.start()].strip() if m else text.strip()
    urls = extract_urls(text)
    remaining = [u for u in urls if canonical_key(u) != tkey]
    if len(remaining) == len(urls):
        return None  # 没找到匹配链接
    if dry_run:
        return True
    # 重建 body: 表头 + 每个剩余 URL 独立 <div> (Notes 中渲染为列表)
    divs = f"<div>{_esc_html(header)}</div>" if header else ""
    for u in remaining:
        divs += f"<div>{_esc_html(u)}</div>"
    if not divs:
        divs = f"<div>{_esc_html(header)}</div>"
    script = (f'tell application "Notes" to set body of '
              f'(first note whose name contains "{NOTE_KW}") to "{divs}"')
    _run_osascript(script)
    return True


if __name__ == "__main__":
    t = read_clip_text()
    print("=== 网页剪藏正文 ===")
    print(t)
    print("\n=== 提取到的 URL ===")
    for u in extract_urls(t):
        print(" ", canonical_key(u), u)
