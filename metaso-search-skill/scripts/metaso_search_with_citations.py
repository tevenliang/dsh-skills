#!/usr/bin/env python3
"""
Metaso Search with Citations — 搜索结果带编号引用，URL 可见。
支持两种模式：
  --mode plain   : 纯格式，给每个结果加 [1][2] 编号 + 链接
  --mode llm     : LLM 增强，生成带编号引用的结构化答案
"""
import sys
import os
import json
import argparse
import subprocess
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SEARCH_PY  = os.path.join(SCRIPT_DIR, "search.py")


def fetch_raw(query: str, size: int = 8) -> list[dict]:
    env = os.environ.copy()
    env["METASO_API_KEY"] = os.environ.get("METASO_API_KEY", "")

    result = subprocess.run(
        [sys.executable, SEARCH_PY, json.dumps({"q": query, "size": size})],
        capture_output=True, text=True, env=env,
        cwd=os.path.dirname(SCRIPT_DIR),
    )
    if result.returncode != 0:
        print(f"API 错误: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"JSON 解析失败，stdout: {result.stdout[:200]}", file=sys.stderr)
        sys.exit(1)

    return data.get("webpages", []), data.get("total", 0)


def format_plain(webpages: list[dict], query: str, total: int) -> str:
    """纯格式：带编号和 URL 的干净列表"""
    lines = [
        f"# 秘塔搜索：{query}",
        f"共找到约 {total} 条结果\n",
        "---",
    ]
    for i, w in enumerate(webpages, 1):
        title   = w.get("title", "无标题")
        link    = w.get("link", "")
        snippet = w.get("snippet", w.get("summary", ""))
        date    = w.get("date", "")
        score   = w.get("score", "")

        lines.append(f"**[{i}] {title}**")
        lines.append(f"   URL: {link}")
        if date:
            lines.append(f"   日期: {date}")
        if score:
            lines.append(f"   质量: {score}")
        if snippet:
            lines.append(f"\n   {snippet}\n")
        lines.append("---")

    return "\n".join(lines)


def build_llm_prompt(webpages: list[dict], query: str) -> str:
    """构造 LLM prompt"""
    refs = []
    for i, w in enumerate(webpages, 1):
        title   = w.get("title", "无标题")
        link    = w.get("link", "")
        snippet = w.get("snippet", w.get("summary", ""))
        refs.append(f"[{i}] {title}\n    URL: {link}\n    摘要: {snippet}")

    return f"""你是一个研究助手。以下是秘塔搜索的结果，请根据这些搜索结果，回答用户的问题。

用户问题：{query}

---
搜索结果：
{chr(10).join(refs)}
---

请按以下格式回答：
1. 先给出一个简洁的总结答案（2-3句话）
2. 然后分点详细说明，每个点都要标注来源，格式为 [来源编号]
3. 最后列出所有参考链接（只需URL）

注意：
- 所有引用必须标注来源编号，如 [1]、[2]
- 如果某个信息来自多个来源，同时标注，如 [1][2]
- 不要编造信息，所有回答都必须有对应的搜索来源支撑
- 用中文回答
"""


def call_llm(prompt: str) -> str:
    """通过 bailian-cli (bl text chat) 调用 LLM"""
    import tempfile, json as _json

    # 优先用 bailian-cli (bl text chat)
    messages = [{"role": "user", "content": prompt}]
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            _json.dump(messages, f)
            tmp = f.name
        result = subprocess.run(
            ["bl", "text", "chat", "--messages-file", tmp, "--model", "qwen3.7-plus", "--max-tokens", "2000"],
            capture_output=True, text=True, timeout=60,
        )
        os.unlink(tmp)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception as e:
        pass

    # fallback: openai 兼容端（非 free 模型，避免配额）
    try:
        import requests
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if api_key:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "qwen/qwen3.5-flash-02-23",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 2000,
                },
                timeout=60,
            )
            if resp.ok:
                return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        pass

    return "[LLM 调用失败，请使用 --mode plain 模式]"


def main():
    parser = argparse.ArgumentParser(description="秘塔搜索（带引用标注）")
    parser.add_argument("query", nargs="?", default="", help="搜索关键词")
    parser.add_argument("-q", dest="query_arg", default="", help="搜索关键词（兼容写法）")
    parser.add_argument("-s", "--size", type=int, default=8, help="结果数量，默认8")
    parser.add_argument("-m", "--mode", choices=["plain", "llm"], default="plain",
                       help="plain=纯格式，llm=LLM增强（带引用标注的完整答案）")
    parser.add_argument("-f", "--format", choices=["json", "text"], default="text",
                       help="输出格式")
    args = parser.parse_args()

    q = args.query or args.query_arg
    if not q:
        print("用法: python metaso_search_with_citations.py '关键词' [-s 数量] [-m plain|llm]", file=sys.stderr)
        sys.exit(1)

    webpages, total = fetch_raw(q, args.size)

    if not webpages:
        print("未找到结果。")
        sys.exit(0)

    if args.format == "json":
        print(json.dumps({"query": q, "total": total, "webpages": webpages}, ensure_ascii=False, indent=2))
        return

    if args.mode == "llm":
        print(f"正在用 LLM 生成带引用的答案（{len(webpages)} 条结果）...\n")
        prompt = build_llm_prompt(webpages, q)
        answer = call_llm(prompt)
        # 在最后附上原始链接列表作为附录
        refs = "\n".join(
            f"[{i}] {w['title']} — {w['link']}"
            for i, w in enumerate(webpages, 1)
        )
        print(answer)
        print("\n---\n**参考来源：**\n" + refs)
    else:
        print(format_plain(webpages, q, total))


if __name__ == "__main__":
    main()
