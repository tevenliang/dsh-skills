#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vault-summary/scripts/summarize_file.py — vault 文件总结（对齐 crawl 总结模块）

输入:  md 文件路径（含 frontmatter 的笔记 / 文章 / 抓取稿）
输出:
  - stdout: 一段 JSON {"summary":..., "topics":[[[emoji,title],[bullet,...]],...], "engine":...}
  - 默认把 `## 总结`（🎯一句话核心 / ⏳速读 / 💡核心金句）注入 md 的 abstract 区
    （frontmatter 之后、第一个 ## 之前），与 crawl 总结模块同款格式

设计对齐（与 ~/.agents/skills/crawl/common-summary/summarize.py）:
- system prompt 取自本 skill 的 scripts/prompt_topics.md 的 `## Prompt` 段（单一真相源）
- 同 JSON schema：{summary, topics}
- 同引擎链：glm-4-flash（zhipu 凭证）主, bailian（`bl` CLI）/ minimax（`mmx` CLI）兜底
- 同健壮性：parse_json_strict + normalize_topics + validate，失败逐引擎重试
- 同注入格式：_format_summary_section / inject_summary_to_md（🎯/⏳/💡）

仅依赖 vault-summary 自带逻辑 + 共享凭证，不 import crawl 内部模块（避免耦合）。
"""
from __future__ import annotations

import sys
import os
import re
import json
import shutil
import urllib.request
import urllib.error
import subprocess
from pathlib import Path

# ── 路径 ──────────────────────────────────────────────────────
SKILL_DIR = Path(__file__).resolve().parent.parent          # .../vault-summary
SCRIPTS_DIR = SKILL_DIR / "scripts"
CRED = Path.home() / ".agents" / "credentials" / "ominicrawl" / "zhipu.json"

# ── 模型 / 参数 ───────────────────────────────────────────────
GLM_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
GLM_MODEL = "glm-4-flash"
MAX_TOKENS = 4000
TEMPERATURE = 0.3
MAX_BODY = 12000          # 送 LLM 的最大正文长度
MIN_CHARS = 100           # 正文低于此不总结

BAILIAN_TEXT_DEFAULT_MODEL = "qwen3.6-flash"
_MINIMAX_DEFAULT_MODEL = "MiniMax-M2.7"

_BAILIAN_BIN = shutil.which("bl") or shutil.which("bailian") or str(Path.home() / ".npm-global" / "bin" / "bailian")
_MMX_BIN = shutil.which("mmx") or str(Path.home() / ".npm-global" / "bin" / "mmx")


# ── system prompt（单一真相源：从 prompt_topics.md 提取，失败回退内嵌）──────────
_FALLBACK_SYSTEM_PROMPT = """你是文章拆解助手。任务：把用户提供的文本（文章/视频转录/播客/任何长内容）拆成结构化总结，让用户完全不用读原文就能掌握全文脉络。

## 输出 JSON 结构（严格遵守，不要任何额外字段、不要 Markdown 包装）
{
  "summary": "一句话总结（≤80字）",
  "topics": [
    [["<emoji>", "<主题标题>"], ["<bullet>", "<bullet>", "<bullet>"]],
    [["<emoji>", "<主题标题>"], ["<bullet>", "<bullet>"]]
  ]
}

## 核心规则

1. **零格式噪声** - 禁止导览前缀、"原文提到"、"作者认为" 等空话开头；bullet 直接说内容。
2. **覆盖度优先** - 必须保留数字、专有名词、对比关系、因果链；禁止抽象成空话。
3. **主题先行层级** - 拆 3-5 个主题板块，主题句 ≤13 字；按原文逻辑递进排列。
4. **emoji 选主题类型** - 按领域/情绪选（💹金融 📉风险 🔒监管 💡观点 🤖AI …），不是装饰。
5. **bullet 句式** - 每条是完整具体事实，不是抽象标签；一段讲 N 个事实拆 N 条。
6. **不发明内容** - 只总结原文，不补充背景、不评价、不预测。

## 输出要求
- 主题 3-5 个，每个主题 bullet 2-5 条
- summary ≤80 字，抓全文核心判断
- 输出语言与原文一致

## 严格执行
- 输出必须是合法 JSON，可被 json.loads() 解析
- 不要输出 JSON 以外的任何内容
- 字段命名严格：summary / topics（小写、复数）
- 主题标题是字符串（不含 emoji），emoji 单独字段
"""


def load_system_prompt() -> str:
    p = SCRIPTS_DIR / "prompt_topics.md"
    if p.exists():
        text = p.read_text(encoding="utf-8")
        m = re.search(r"##\s*Prompt\b.*?\n```\n(.*?)\n```", text, re.S)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return _FALLBACK_SYSTEM_PROMPT


SYSTEM_PROMPT = load_system_prompt()


# ── frontmatter / 正文 ────────────────────────────────────────
def strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        m = re.search(r"^---\n.*?\n---\n", text, re.S)
        if m:
            return text[m.end():].strip()
    return text.strip()


# ── 引擎：GLM-4-flash（zhipu）────────────────────────────────
def get_key() -> str:
    if not CRED.exists():
        return ""
    try:
        return json.loads(CRED.read_text()).get("api_key", "")
    except Exception:
        return ""


def call_glm(system: str, user_content: str, api_key: str) -> str:
    payload = {
        "model": GLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        GLM_ENDPOINT,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"GLM 异常: {e}")
    choices = result.get("choices") or []
    if not choices:
        raise RuntimeError(f"GLM 无 choices: {json.dumps(result)[:200]}")
    return choices[0].get("message", {}).get("content", "")


# ── 引擎：bailian（`bl` CLI）─────────────────────────────────
def _bailian_run(cmd, timeout):
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return stdout or "", stderr or "", proc.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), 9)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.communicate(timeout=2)
        except Exception:
            pass
        raise


def call_bailian_text(system, user_content, model=None, timeout=180, max_tokens=None, temperature=None):
    model = model or BAILIAN_TEXT_DEFAULT_MODEL
    cmd = [
        _BAILIAN_BIN, "text", "chat",
        "--model", model,
        "--system", system,
        "--message", user_content,
        "--max-tokens", str(max_tokens or MAX_TOKENS),
        "--temperature", str(temperature if temperature is not None else TEMPERATURE),
        "--quiet",
    ]
    try:
        stdout, stderr, rc = _bailian_run(cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"bailian text 超时 {timeout}s")
    if rc != 0:
        raise RuntimeError(f"bailian text rc={rc}: {(stderr or stdout)[:200]}")
    return stdout


# ── 引擎：minimax（`mmx` CLI）────────────────────────────────
def call_minimax_text(system, user_content, model=None, timeout=180):
    model = model or _MINIMAX_DEFAULT_MODEL
    cmd = [
        _MMX_BIN, "text", "chat",
        "--model", model,
        "--system", system,
        "--message", user_content,
        "--max-tokens", str(MAX_TOKENS),
        "--temperature", str(TEMPERATURE),
        "--quiet", "--output", "text",
    ]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), 9)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.communicate(timeout=2)
        except Exception:
            pass
        raise RuntimeError(f"minimax 超时 {timeout}s")
    if proc.returncode != 0:
        raise RuntimeError(f"minimax rc={proc.returncode}: {(stderr or stdout)[:200]}")
    return (stdout or "").strip()


# ── JSON 容错 ─────────────────────────────────────────────────
def parse_json_strict(text: str):
    """Robust JSON parser: handles markdown code blocks, unescaped newlines in strings."""
    s = text.strip()
    m = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", s, re.S)
    if m:
        s = m.group(1).strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"JSON not found in: {s[:200]}")
    s = s[start:end + 1]
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # Fix unescaped newlines inside string values
        fixed = []
        i, in_str, esc = 0, False, False
        while i < len(s):
            c = s[i]
            if esc:
                fixed.append(c); esc = False
            elif c == '\\' and in_str:
                fixed.append(c); esc = True
            elif c == '"' and not esc:
                in_str = not in_str; fixed.append(c)
            elif c == '\n' and in_str:
                fixed.append('\\n')
            elif c == '\r' and in_str:
                pass
            else:
                fixed.append(c)
            i += 1
        try:
            return json.loads(''.join(fixed))
        except json.JSONDecodeError:
            # Last resort: regex extract summary and topics
            sm = re.search(r'"summary"\s*:\s*"([^"]{0,200})"', s)
            tm = re.findall(r'"topics"\s*:\s*(\[.*\])', s, re.S)
            if sm and tm:
                try:
                    topics = json.loads(tm[-1])
                except:
                    topics = []
                return {"summary": sm.group(1), "topics": topics}
            raise ValueError(f"JSON recovery failed for: {s[:200]}")

def normalize_topics(topics):
    fixed = []
    for t in topics:
        if not isinstance(t, list):
            continue
        flat = []
        def flatten(x):
            if isinstance(x, str):
                flat.append(x)
            elif isinstance(x, list):
                for it in x:
                    flatten(it)
            else:
                flat.append(str(x))
        for it in t:
            flatten(it)
        if len(flat) < 3:
            continue
        emoji, title = flat[0], flat[1]
        bullets = flat[2:]
        if len(title) > 13:
            title = title[:13]
        # 清掉模型偶尔加的前导列表符号（- / * / •），注入时统一由 _format_summary_section 加
        bullets = [re.sub(r"^[-*\u2022]\s+", "", b).strip() for b in bullets if b and b.strip()]
        if bullets:
            fixed.append([[emoji, title], bullets])
    return fixed


def validate(obj):
    if not isinstance(obj, dict):
        raise ValueError("顶层不是 dict")
    if not isinstance(obj.get("summary"), str) or not obj["summary"].strip():
        raise ValueError("summary 缺失/非字符串")
    if len(obj["summary"]) > 200:
        obj["summary"] = obj["summary"][:200]
    topics = obj.get("topics")
    if not isinstance(topics, list) or len(topics) < 2:
        raise ValueError(f"topics 应为 ≥2 个主题, 实际 {type(topics).__name__}")
    topics = normalize_topics(topics)
    if len(topics) < 1:
        raise ValueError(f"normalize 后 topics 不足 1 个: {len(topics)}")
    if len(topics) > 5:
        topics = topics[:5]
    for i, t in enumerate(topics):
        if not isinstance(t, list) or len(t) != 2:
            raise ValueError(f"topic[{i}] 应为 2 元素 list")
        title_emoji, bullets = t
        if not isinstance(title_emoji, list) or len(title_emoji) != 2:
            raise ValueError(f"topic[{i}].title_emoji 应为 [emoji, title]")
        emoji, title = title_emoji
        if not isinstance(emoji, str) or not isinstance(title, str) or not title.strip():
            raise ValueError(f"topic[{i}] emoji/title 类型错或为空")
        if not isinstance(bullets, list) or not bullets:
            raise ValueError(f"topic[{i}].bullets 应为非空 list")
        bullets = [str(b).strip() for b in bullets if str(b).strip()]
        if not bullets:
            raise ValueError(f"topic[{i}] bullets 全空")
        t[0] = [emoji, title]
        t[1] = bullets
    obj["topics"] = topics
    return obj


# ── 注入格式（与 crawl 同款 🎯/⏳/💡）─────────────────────────
def _format_summary_section(obj):
    summary = (obj.get("summary") or "").strip()
    topics = obj.get("topics") or []
    lines = ["## 总结", ""]
    if summary:
        lines += ["🎯 一句话核心：", summary, ""]
    speedread_lines = []
    for topic in topics:
        if not isinstance(topic, list) or len(topic) != 2:
            continue
        title_emoji, bullets = topic
        if not isinstance(title_emoji, list) or len(title_emoji) != 2:
            continue
        emoji, title = title_emoji
        bullet_list = bullets if isinstance(bullets, list) else []
        if not bullet_list:
            continue
        speedread_lines.append(f"- {emoji} **{title}**")
        for b in bullet_list:
            speedread_lines.append(f"  - {b}")
    if speedread_lines:
        lines += ["⏳ 速读", ""] + speedread_lines + [""]
    quotes = []
    for topic in topics:
        if not isinstance(topic, list) or len(topic) != 2:
            continue
        _, bullets = topic
        if not isinstance(bullets, list):
            continue
        for b in bullets:
            bs = str(b).strip()
            if 8 <= len(bs) <= 60 and "。" in bs and bs not in quotes:
                quotes.append(bs)
                break
    if quotes:
        lines += ["💡 核心金句", ""]
        for q in quotes[:5]:
            lines.append(f"- {q}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _strip_summary_section(text):
    return re.sub(r"\n+## 总结\s*\n[\s\S]*?(?=\n## |\Z)", "", text)


def inject_summary_to_md(md_path, obj, overwrite=False):
    p = Path(md_path)
    text = p.read_text(encoding="utf-8")
    text = _strip_summary_section(text)            # 先清掉任何已有 ## 总结（避免重复）

    frontmatter = ""
    body = text
    if body.startswith("---"):
        m = re.search(r"^---\n.*?\n---\n", body, re.S)
        if m:
            frontmatter = body[:m.end()]
            body = body[m.end():]
    # abstract 区结束锚点：第一个标题（# 或 ##）之后；无标题则追加到末尾
    first_heading = re.search(r"^#{1,6}\s.*$", body, re.MULTILINE)
    if first_heading:
        abstract = body[:first_heading.end()].rstrip()
        rest = body[first_heading.end():]
    else:
        abstract = body.rstrip()
        rest = ""

    if not overwrite and re.search(r"^##\s*总结\s*$", abstract, re.M):
        return False

    summary_md = _format_summary_section(obj)
    sep = "\n\n" if abstract else ""
    new_body = abstract + sep + summary_md + "\n\n" + rest.lstrip()
    p.write_text(frontmatter + new_body, encoding="utf-8")
    return True


# ── 主流程 ────────────────────────────────────────────────────
def summarize_text(body_text, engine="auto", model=None, min_chars=MIN_CHARS, body_max=MAX_BODY):
    body = (body_text or "").strip()
    if len(body) < min_chars:
        raise RuntimeError(f"正文仅 {len(body)} 字符 (<{min_chars}), 跳过总结")
    user = body[:body_max]
    last_err = None
    engines = ["bailian", "glm", "minimax"] if engine == "auto" else [engine]
    for eng in engines:
        try:
            if eng == "glm":
                api_key = get_key()
                if not api_key:
                    raise RuntimeError("无 GLM API key")
                raw = call_glm(SYSTEM_PROMPT, user, api_key)
            elif eng == "bailian":
                if not _BAILIAN_BIN or not shutil.which("bl"):
                    raise RuntimeError("无 bl CLI")
                raw = call_bailian_text(SYSTEM_PROMPT, user, model=model)
            elif eng == "minimax":
                if not _MMX_BIN or not shutil.which("mmx"):
                    raise RuntimeError("无 mmx CLI")
                raw = call_minimax_text(SYSTEM_PROMPT, user)
            else:
                raise RuntimeError(f"未知引擎: {eng}")
            obj = parse_json_strict(raw)
            obj = validate(obj)
            obj["engine"] = eng
            return obj
        except Exception as e:
            last_err = e
            print(f"  [summarize] engine={eng} 失败: {e}", file=sys.stderr, flush=True)
            continue
    raise RuntimeError(f"总结失败 (所有引擎): {last_err}")


def main():
    import argparse
    ap = argparse.ArgumentParser(description="vault 文件总结（对齐 crawl 总结模块）")
    ap.add_argument("md_path", help="要总结的 md 文件路径")
    ap.add_argument("--engine", default="auto", choices=["auto", "glm", "bailian", "minimax"])
    ap.add_argument("--no-inject", action="store_true", help="只输出 JSON，不写回 md")
    ap.add_argument("--overwrite", action="store_true", help="覆盖已有 ## 总结 段")
    ap.add_argument("--body-max", type=int, default=MAX_BODY)
    ap.add_argument("--min-chars", type=int, default=MIN_CHARS)
    args = ap.parse_args()

    p = Path(args.md_path)
    if not p.exists():
        sys.stderr.write(f"❌ 文件不存在: {p}\n")
        sys.exit(1)

    md = p.read_text(encoding="utf-8")
    body = strip_frontmatter(md)
    if len(body) < args.min_chars:
        sys.stderr.write(f"❌ 正文仅 {len(body)} 字符 (<{args.min_chars}), 跳过\n")
        sys.exit(1)

    try:
        obj = summarize_text(body, engine=args.engine, min_chars=args.min_chars, body_max=args.body_max)
    except Exception as e:
        sys.stderr.write(f"❌ {e}\n")
        sys.exit(2)

    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()

    if not args.no_inject:
        try:
            ok = inject_summary_to_md(p, obj, overwrite=args.overwrite)
            if ok:
                sys.stderr.write(f"✅ 已注入 ## 总结 到 {p}\n")
            else:
                sys.stderr.write(f"ℹ️ 已有 ## 总结 段，未覆盖（用 --overwrite 强制）\n")
        except Exception as e:
            sys.stderr.write(f"⚠️ 注入失败: {e}\n")


if __name__ == "__main__":
    main()
