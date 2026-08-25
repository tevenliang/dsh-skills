"""
bili_wbi.py — 替换 Evil0ctal BilibiliWebCrawler 的 thin wrapper

修复:
1. 动态 wbi mixin_key (从 /x/web-interface/nav 拉, LRU 缓存 6h)
2. v_voucher 二次校验: code:-352 + v_voucher → 拿 v_voucher 访问 nav 换新 bili_ticket → 重试
3. 支持外部 cookie 注入 (不依赖 Evil0ctal config.yaml)

接口:
    async with BilibiliWbi(cookie="...") as bili:
        data = await bili.fetch_user_post_videos(mid=3706949765958513, pn=1)
"""
import asyncio
import hashlib
import json
import re
import time
from typing import Optional
import httpx
from pathlib import Path

# 复用 wbi_keys
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "lib" / "douyin_api"))
from crawlers.bilibili.web.wbi_keys import fetch_mixin_key, get_cached_mixin_key

USER_POST = "https://api.bilibili.com/x/space/wbi/arc/search"
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"

DEFAULT_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0.0.0 Safari/537.36")

DEFAULT_HEADERS_BASE = {
    "User-Agent": DEFAULT_UA,
    "Referer": "https://space.bilibili.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Origin": "https://space.bilibili.com",
}

# bili_ticket 在 cookie 里的有效期 (秒), B 站一般 30 天
TICKET_TTL = 30 * 24 * 3600


def _calc_w_rid(params: dict, mixin_key: str) -> str:
    """B 站 WBI 签名: md5(按字典序排序的 query + mixin_key)"""
    # 1. 加 wts
    params = dict(params)
    params['wts'] = str(int(time.time()))
    # 2. 按 key 排序
    params = dict(sorted(params.items()))
    # 3. 过滤 !'()* 字符
    params = {
        k: ''.join(c for c in str(v) if c not in "!'()*")
        for k, v in params.items()
    }
    # 4. urlencode (默认 quote_plus 会把空格变 +, B 站要 %20)
    from urllib.parse import urlencode
    query = urlencode(params)
    # 5. 加 mixin_key 算 MD5
    return hashlib.md5((query + mixin_key).encode()).hexdigest()


def _parse_cookie_string(cookie_str: str) -> dict:
    """从 'k1=v1; k2=v2' 解析为 dict"""
    out = {}
    for part in cookie_str.split(';'):
        part = part.strip()
        if '=' in part:
            k, v = part.split('=', 1)
            out[k.strip()] = v.strip()
    return out


def _serialize_cookie(cookie_dict: dict) -> str:
    """dict → 'k1=v1; k2=v2'"""
    return '; '.join(f"{k}={v}" for k, v in cookie_dict.items())


class BilibiliWbi:
    def __init__(self, cookie: str, max_retries: int = 5):
        self.cookie_str = cookie
        self.cookie_dict = _parse_cookie_string(cookie) if cookie else {}
        self.max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None
        # 触发过 v_voucher 后记录是否换了 ticket, 防止无限循环
        self._voucher_used = False

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=15)
        # 启动时拉一次 mixin_key
        await fetch_mixin_key()
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    def _headers(self, with_cookie: bool = True) -> dict:
        h = dict(DEFAULT_HEADERS_BASE)
        if with_cookie and self.cookie_str:
            h['Cookie'] = self.cookie_str
        return h

    async def _refresh_ticket_via_voucher(self, v_voucher: str) -> bool:
        """
        用 v_voucher 在 /x/web-interface/nav 换新 bili_ticket
        成功: 更新 self.cookie_dict 和 self.cookie_str, 返回 True
        失败: 返回 False
        """
        if not self.cookie_str:
            return False  # 没 cookie 没法换
        h = self._headers(with_cookie=True)
        h['X-Web-Voucher'] = v_voucher
        try:
            r = await self._client.get(NAV_URL, headers=h)
        except Exception as e:
            return False
        try:
            d = r.json()
        except Exception:
            return False
        if d.get('code') != 0:
            return False
        data = d.get('data', {})
        if not data.get('isLogin'):
            return False
        # 提取新 bili_ticket 和 buvid3 (如果有)
        new_ticket = data.get('bili_ticket')
        new_ticket_expires = data.get('bili_ticket_expires')
        if new_ticket:
            self.cookie_dict['bili_ticket'] = new_ticket
            if new_ticket_expires:
                self.cookie_dict['bili_ticket_expires'] = str(new_ticket_expires)
            else:
                self.cookie_dict['bili_ticket_expires'] = str(int(time.time()) + TICKET_TTL)
        # 同时刷一下 buvid3 / _uuid (B 站返回的 cookies 字段, 需要在 nav 返回里找)
        refresh_cookies = data.get('refresh_cookies', [])
        for c in refresh_cookies:
            name = c.get('name')
            value = c.get('value')
            if name and value:
                self.cookie_dict[name] = value
        # 重新序列化
        self.cookie_str = _serialize_cookie(self.cookie_dict)
        return True

    async def fetch_user_post_videos(self, mid: str, pn: int = 1, ps: int = 20) -> dict:
        """
        抓 B 站某个 UP 主最新视频
        流程: wbi 接口 → 触发 -352 → v_voucher 换 ticket → 重试
        """
        if not self._client:
            raise RuntimeError("BilibiliWbi 必须用 async with 包裹")

        for attempt in range(self.max_retries):
            mixin_key = await fetch_mixin_key()
            params = {
                "mid": str(mid),
                "pn": str(pn),
                "ps": str(ps),
            }
            w_rid = _calc_w_rid(params, mixin_key)
            params['wts'] = str(int(time.time()) - 1)  # _calc_w_rid 会覆盖, 但 query 里要带
            # 重新算一次, 把 wts 拼到 query 里
            from urllib.parse import urlencode
            params_with_wts = dict(params)
            params_with_wts['wts'] = str(int(time.time()) - 1)
            # 重新排序 + 过滤 + 算 w_rid (跟 _calc_w_rid 一样)
            sorted_p = dict(sorted(params_with_wts.items()))
            filt_p = {k: ''.join(c for c in str(v) if c not in "!'()*") for k, v in sorted_p.items()}
            query = urlencode(filt_p)
            w_rid = hashlib.md5((query + mixin_key).encode()).hexdigest()
            url = f"{USER_POST}?{query}&w_rid={w_rid}"
            try:
                r = await self._client.get(url, headers=self._headers())
            except Exception as e:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2)
                    continue
                raise
            try:
                data = r.json()
            except Exception:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2)
                    continue
                raise RuntimeError(f"非 JSON 响应: {r.text[:200]}")

            # -352 是 B 站 WBI 风控：有 v_voucher 时先换 ticket；没有 voucher
            # 也可能只是瞬时校验失败，不能直接当成“空视频列表”。有限退避重试。
            if data.get('code') == -352:
                if not self._voucher_used:
                    v_voucher = (data.get('data') or {}).get('v_voucher')
                    if v_voucher:
                        self._voucher_used = True
                        await self._refresh_ticket_via_voucher(v_voucher)
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(min(0.8 * (attempt + 1), 3.0))
                    continue
            return data
        return data  # 最后的尝试

    async def get_user_profile(self, mid: str) -> dict:
        """简单 nav 接口, 看登录态"""
        r = await self._client.get(NAV_URL, headers=self._headers())
        return r.json()


# CLI 入口: 用于单点测试
async def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="测试 B 站 WBI 抓取")
    parser.add_argument("mid", help="UP 主 mid")
    parser.add_argument("--cookie", help="Cookie 字符串 (可选)")
    args = parser.parse_args()
    cookie = args.cookie
    if not cookie:
        # 尝试从环境变量读
        cookie = None
    async with BilibiliWbi(cookie=cookie) as bili:
        data = await bili.fetch_user_post_videos(mid=args.mid)
        print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])


if __name__ == '__main__':
    asyncio.run(_cli())
