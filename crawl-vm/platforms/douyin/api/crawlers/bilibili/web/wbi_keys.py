"""
wbi_keys.py — 动态从 B 站 /x/web-interface/nav 拉最新 wbi mixin_key

B 站的 WBI mixin_key 大约 30 天换一次, 写死在代码里会过期导致 -352 风控。
本工具每次请求前动态拉取, 用 LRU 缓存 (默认 6 小时刷新一次)。
"""
import asyncio
import hashlib
import time
import re
import httpx
from functools import lru_cache

NAV_URL = "https://api.bilibili.com/x/web-interface/nav"

# B 站 mixin_key 重排下标 (公开社区资料)
_MIXIN_KEY_ORDER = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
]

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

_cache = {"mixin_key": None, "ts": 0, "ttl": 6 * 3600}  # 默认 6 小时
_lock = asyncio.Lock()


def _calc_mixin_key(img_key: str, sub_key: str) -> str:
    raw = img_key + sub_key
    return "".join(raw[i] for i in _MIXIN_KEY_ORDER if i < len(raw))


def _extract_key(url: str) -> str:
    """从 https://i0.hdslb.com/bfs/wbi/<32hex>.png 提取 32 字符 key"""
    m = re.search(r"/([0-9a-f]{32})\.png", url)
    if not m:
        raise ValueError(f"无法从 {url} 提取 wbi key")
    return m.group(1)


async def fetch_mixin_key(force_refresh: bool = False) -> str:
    """
    拉取最新 wbi mixin_key (带缓存)

    Args:
        force_refresh: 强制刷新 (用于 token 过期时)
    Returns:
        32 字符的 mixin_key
    """
    now = time.time()
    if not force_refresh and _cache["mixin_key"] and (now - _cache["ts"]) < _cache["ttl"]:
        return _cache["mixin_key"]

    async with _lock:
        # 双重检查 (避免并发重复拉)
        if not force_refresh and _cache["mixin_key"] and (time.time() - _cache["ts"]) < _cache["ttl"]:
            return _cache["mixin_key"]

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(NAV_URL, headers=DEFAULT_HEADERS)
            data = resp.json()
        wbi = data.get("data", {}).get("wbi_img", {})
        img_url = wbi.get("img_url", "")
        sub_url = wbi.get("sub_url", "")
        if not img_url or not sub_url:
            raise RuntimeError(f"nav 接口未返回 wbi_img: code={data.get('code')} msg={data.get('message')}")

        img_key = _extract_key(img_url)
        sub_key = _extract_key(sub_url)
        mixin_key = _calc_mixin_key(img_key, sub_key)
        _cache["mixin_key"] = mixin_key
        _cache["ts"] = time.time()
        return mixin_key


def get_cached_mixin_key() -> str:
    """同步获取缓存中的 mixin_key, 没有就抛错"""
    if not _cache["mixin_key"]:
        raise RuntimeError("wbi mixin_key 尚未初始化, 请先 await fetch_mixin_key()")
    return _cache["mixin_key"]


def reset_cache():
    """测试用: 重置缓存"""
    _cache["mixin_key"] = None
    _cache["ts"] = 0


if __name__ == "__main__":
    async def _test():
        key = await fetch_mixin_key(force_refresh=True)
        print(f"mixin_key: {key}")
        # 验证: B 站 WBI 测试
        import time as _t
        wts = int(_t.time())
        test_q = f"mid=3706949765958513&pn=1&ps=20&wts={wts}"
        test_q_with_mixin = test_q + key
        w_rid = hashlib.md5(test_q_with_mixin.encode()).hexdigest()
        print(f"test_w_rid: {w_rid}")
        url = f"https://api.bilibili.com/x/space/wbi/arc/search?{test_q}&w_rid={w_rid}"
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=DEFAULT_HEADERS)
            print(f"status: {r.status_code}, body: {r.text[:300]}")
    asyncio.run(_test())
