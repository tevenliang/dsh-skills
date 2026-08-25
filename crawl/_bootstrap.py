import sys, os
ROOT = os.path.dirname(os.path.abspath(__file__))
# 平台内部裸包名（crawlers / bili_feed / wbi 等）在原单体靠把这些源码目录加进 sys.path 才能 import
_PLATFORM_PATHS = [
    os.path.join(ROOT, "ingest-douyin", "douyin_api"),
    os.path.join(ROOT, "ingest-douyin", "douyin"),
    os.path.join(ROOT, "ingest-bilibili", "bilibili"),
    os.path.join(ROOT, "ingest-xhs", "xiaohongshu"),
    os.path.join(ROOT, "ingest-wx"),
]
for p in [ROOT] + _PLATFORM_PATHS:
    if p not in sys.path:
        sys.path.append(p)

# 2026-07-21: 不再 strip proxy — VPN 软件按域名自动路由, 代码层不干预
# (历史: 此处曾剥 HTTP_PROXY/HTTPS_PROXY/NO_PROXY="*" 强制直连, 现已移除)
