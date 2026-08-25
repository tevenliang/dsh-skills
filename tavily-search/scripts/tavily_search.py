#!/usr/bin/env python3
"""
Tavily AI Search CLI

按 SKILL.md 描述实现参数,默认输出 Markdown, --json 输出原始 JSON。
Key 从 ~/.agents/credentials/tavily.json 读取,不接受命令行传 key。

用法:
    tavily_search.py "搜索关键词" [选项]

依赖: 纯 stdlib (urllib)
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

TAVILY_ENDPOINT = "https://api.tavily.com/search"
# 优先读 SKILL.md 写的 ~/.codex 路径,兼容老安装回退 ~/.claude
_CODEx_CRED = Path.home() / ".agents" / "credentials" / "tavily.json"
_CLAUDE_CRED = Path.home() / ".claude" / "credentials" / "tavily.json"
CRED_FILE = _CODEx_CRED if _CODEx_CRED.exists() else _CLAUDE_CRED


def load_api_key() -> str:
    """从固定路径读取 API key。失败时给出可执行的修复提示。"""
    if not CRED_FILE.exists():
        print(
            f"❌ 凭证文件不存在: {CRED_FILE}\n"
            f"   修复: 创建目录并写入 {{'api_key': 'your-key-here'}}",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        data = json.loads(CRED_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"❌ 凭证文件不是合法 JSON: {e}", file=sys.stderr)
        sys.exit(1)
    key = data.get("api_key", "").strip()
    if not key:
        print(f"❌ 凭证文件里没有 api_key 字段", file=sys.stderr)
        sys.exit(1)
    return key


def search(args: argparse.Namespace) -> dict:
    """调用 Tavily /search 端点,返回原始 JSON 响应。"""
    payload = {
        "api_key": load_api_key(),
        "query": args.query,
        "topic": args.topic,
        "search_depth": args.depth,
        "max_results": args.max_results,
        "include_answer": not args.no_answer,
        "include_raw_content": args.raw_content,
        "include_images": args.images,
    }
    if args.include_domains:
        payload["include_domains"] = args.include_domains
    if args.exclude_domains:
        payload["exclude_domains"] = args.exclude_domains

    req = urllib.request.Request(
        TAVILY_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"❌ Tavily API 错误 {e.code}: {body}", file=sys.stderr)
        sys.exit(2)
    except urllib.error.URLError as e:
        print(f"❌ 网络错误: {e.reason}", file=sys.stderr)
        sys.exit(3)


def render_markdown(data: dict, args: argparse.Namespace) -> str:
    """把响应渲染为人类可读的 Markdown。"""
    out = []
    if data.get("answer") and not args.no_answer:
        out.append(f"## 摘要\n\n{data['answer']}\n")
    results = data.get("results", [])
    if results:
        out.append(f"## 搜索结果 ({len(results)} 条)\n")
        for i, r in enumerate(results, 1):
            out.append(f"### {i}. {r.get('title', '(无标题)')}")
            out.append(f"- **URL**: {r.get('url', '')}")
            out.append(f"- **相关度**: {r.get('score', 0):.2f}")
            if r.get("content"):
                out.append(f"\n{r['content']}\n")
            if r.get("raw_content") and args.raw_content:
                out.append(f"\n<details><summary>原始内容</summary>\n\n{r['raw_content'][:2000]}\n\n</details>\n")
    if data.get("images") and args.images:
        out.append("## 相关图片\n")
        for img in data["images"][:10]:
            if isinstance(img, dict):
                out.append(f"- ![]({img.get('url', '')})")
            else:
                out.append(f"- {img}")
    if not out:
        out.append("（无结果）")
    return "\n".join(out)


def main() -> int:
    p = argparse.ArgumentParser(
        prog="tavily_search.py",
        description="Tavily AI Search — 联网搜索/新闻/AI 摘要",
    )
    p.add_argument("query", help="搜索关键词")
    p.add_argument(
        "--depth",
        choices=["basic", "advanced"],
        default="basic",
        help="basic=快(默认) / advanced=深度(5-10s)",
    )
    p.add_argument(
        "--topic",
        choices=["general", "news"],
        default="general",
        help="general=通用 / news=最近 7 天新闻",
    )
    p.add_argument(
        "--max-results",
        type=int,
        default=5,
        choices=range(1, 11),
        metavar="N",
        help="结果数量 1-10 (默认 5)",
    )
    p.add_argument("--no-answer", action="store_true", help="不要 AI 摘要")
    p.add_argument(
        "--raw-content", action="store_true", help="包含原始网页内容"
    )
    p.add_argument("--images", action="store_true", help="包含相关图片")
    p.add_argument(
        "--include-domains",
        nargs="+",
        metavar="DOMAIN",
        help="限定域名列表(空格分隔)",
    )
    p.add_argument(
        "--exclude-domains",
        nargs="+",
        metavar="DOMAIN",
        help="排除域名列表(空格分隔)",
    )
    p.add_argument("--json", dest="as_json", action="store_true", help="输出原始 JSON")
    args = p.parse_args()

    data = search(args)
    if args.as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(data, args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
