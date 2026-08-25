#!/usr/bin/env python3
"""一次性重试 hot window 内缺失的 LLM 总结。

GLM 被内容审核拦截时，改用 mmx MiniMax 生成总结。成功后把标准化的
``## 总结`` 段注入原始 markdown；脚本只处理当前没有总结段的笔记，重复执行安全。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

SKILL = Path("/Users/tianwenliang/.agents/skills/crawl")
sys.path.insert(0, str(SKILL))
from common.summarize import (  # noqa: E402
    MAX_BODY,
    SYSTEM_PROMPT,
    call_glm,
    get_key,
    has_summary_section,
    inject_summary_to_md,
    parse_json_strict,
    strip_frontmatter,
    validate,
)

# 普通 M2.7 的结构化 JSON 输出比 highspeed 稳定；仍可用 MMX_MODEL 覆盖。
MMX_MODEL = os.environ.get("MMX_MODEL", "MiniMax-M2.7")
MMX_SYSTEM_PROMPT = SYSTEM_PROMPT + """

【本次调用的 MiniMax 输出格式】
为了避免数组嵌套错误，topics 必须输出为对象数组，不要输出原提示中的嵌套数组格式：
{
  "summary": "一句话总结",
  "topics": [
    {"emoji": "💡", "title": "主题标题", "bullets": ["事实1", "事实2"]},
    {"emoji": "📊", "title": "主题标题", "bullets": ["事实1", "事实2"]}
  ]
}
只输出合法 JSON，不要 Markdown 代码块。topics 输出 3-5 个对象；每个对象只包含
emoji、title、bullets 三个字段。bullets 必须是字符串数组。
"""


def _extract_mmx_content(output: dict) -> str:
    """兼容 mmx 当前 content 列表和 OpenAI choices 两种返回形状。"""
    content = output.get("content")
    if isinstance(content, list):
        text = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text.append(part.get("text", ""))
        content = "".join(text)
    if not content:
        choices = output.get("choices") or []
        if choices:
            message = choices[0].get("message", {}) or {}
            content = message.get("content", "")
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError(f"mmx no text content: {json.dumps(output, ensure_ascii=False)[:240]}")
    return content.strip()


def _normalize_mmx_obj(obj: dict) -> dict:
    """把 MiniMax 的对象 topics 转成项目既有的数组 topics。"""
    if not isinstance(obj, dict):
        raise ValueError("mmx 顶层不是对象")
    topics = obj.get("topics")
    if not isinstance(topics, list):
        return obj

    normalized = []
    for topic in topics:
        if isinstance(topic, dict):
            emoji = topic.get("emoji", "")
            title = topic.get("title", "")
            # M2.7 偶发把 bullets 拼成 bullutes，兼容这个已观察到的输出错误。
            bullets = (
                topic.get("bullets")
                or topic.get("bullutes")
                or topic.get("bullet_points")
                or topic.get("points")
            )
            if isinstance(bullets, str):
                bullets = [bullets]
            if isinstance(emoji, str) and isinstance(title, str) and isinstance(bullets, list):
                normalized.append(
                    [[emoji, title], [str(b).strip() for b in bullets if str(b).strip()]]
                )
        else:
            # 如果模型仍按旧数组格式返回，交给 summarize.py 的 normalize_topics 处理。
            normalized.append(topic)
    if normalized:
        obj["topics"] = normalized
    return obj


def _parse_and_validate_mmx(content: str) -> dict:
    obj = parse_json_strict(content)
    return validate(_normalize_mmx_obj(obj))


def call_mmx(system: str, user: str) -> str:
    """调用 MiniMax；输出无法解析或结构不合规时重试一次。"""
    last_err = None
    for _attempt in range(2):
        cmd = [
            "mmx",
            "text",
            "chat",
            "--model",
            MMX_MODEL,
            "--system",
            MMX_SYSTEM_PROMPT,
            "--message",
            user,
            "--output",
            "json",
            "--temperature",
            "0.1",
            "--max-tokens",
            "4000",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired as exc:
            last_err = f"mmx timeout: {exc}"
            continue
        except FileNotFoundError:
            raise RuntimeError("mmx CLI not found") from None
        if result.returncode != 0:
            last_err = f"mmx exit({result.returncode}): {result.stderr[:240]}"
            continue
        try:
            outer = json.loads(result.stdout)
            content = _extract_mmx_content(outer)
            obj = _parse_and_validate_mmx(content)
            return json.dumps(obj, ensure_ascii=False)
        except Exception as exc:
            last_err = f"mmx output invalid: {str(exc)[:180]}"
            continue
    raise RuntimeError(f"mmx failed after 2 attempts: {last_err}")


def summarize_with_fallback(md_path: Path) -> dict:
    md_text = md_path.read_text(encoding="utf-8")
    body = strip_frontmatter(md_text)
    if len(body) < 100:
        raise RuntimeError(f"body too short ({len(body)} <100)")
    user = body[:MAX_BODY]

    api_key = get_key()
    if not api_key:
        raise RuntimeError("no GLM key")
    try:
        raw = call_glm(SYSTEM_PROMPT, user, api_key)
        return validate(parse_json_strict(raw))
    except Exception as glm_err:
        err_str = str(glm_err)
        if "contentFilter" not in err_str and "GLM" not in err_str:
            raise
        print("[GLM->mmx]", end=" ", flush=True)
        return validate(parse_json_strict(call_mmx(SYSTEM_PROMPT, user)))


def collect_targets() -> list[Path]:
    targets = []
    for platform in ("bilibili", "douyin"):
        platform_dir = SKILL / "notes" / platform
        if not platform_dir.exists():
            continue
        for path in platform_dir.rglob("*.md"):
            if path.name.startswith(".") or path.name == "section.md":
                continue
            if any("·" in part for part in path.parts):
                continue
            if not re.match(r"^\d{6}-", path.name):
                continue
            if path.name[:6] < "260620":
                continue
            if has_summary_section(path):
                continue
            targets.append(path)
    return sorted(targets)


def main() -> None:
    targets = collect_targets()
    print(f"target: {len(targets)} (hot window + no ##总结)")
    print()

    injected = skipped = failed = 0
    for index, md_path in enumerate(targets, 1):
        relative = str(md_path.relative_to(SKILL / "notes"))
        print(f"[{index}/{len(targets)}] {relative}", end=" ", flush=True)
        try:
            obj = summarize_with_fallback(md_path)
            if inject_summary_to_md(md_path, obj):
                injected += 1
                print("OK")
            else:
                skipped += 1
                print("SKIP (already has summary)")
        except Exception as exc:
            failed += 1
            print(f"FAIL {str(exc)[:160]}")

    print(f"\n=== done: injected={injected} skipped={skipped} failed={failed} ===")


if __name__ == "__main__":
    main()
