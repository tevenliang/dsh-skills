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
# -*- coding: utf-8 -*-
"""
link-crawl/scripts/summarize.py — 通用内容总结 (主题-bullet 模式, 与 summarize-expert 对齐)

输入:  md 文件路径 (含 frontmatter 的笔记)
输出:  写到 stdout 一段 JSON
       {
         "summary": "一句话总结",
         "topics": [[[emoji, title], [bullet, ...]], ...]
       }
       失败时 stdout 输出 {"error": "..."}

设计:
- prompt 内嵌 (与 ~/.agents/skills/summarize-expert/scripts/prompt_topics.md 同步)
  - 单一真相源 = summarize-expert 的 prompt_topics.md
  - 本脚本复制 prompt 段做 runtime system message
  - 两边手动同步时, 修改 summarize-expert 后镜像到本脚本
- API: 智谱 GLM-4-flash (与 subscription-crawl/common/llm.py 同款)
  - key 读 ~/.agents/credentials/ominicrawl/zhipu.json
  - HTTP 独立实现, 不依赖 subscription-crawl 模块
- 强校验: 解析失败 → 重试 1 次 → 仍失败 → exit 2 + stderr 报告
"""
import sys
import os
import shutil
import re
import json
import urllib.request
import urllib.error
from pathlib import Path

CRED = Path.home() / ".agents" / "credentials" / "ominicrawl" / "zhipu.json"
ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
MODEL = "glm-4-flash"
MAX_TOKENS = 4000
TEMPERATURE = 0.3
MAX_BODY = 12000

# ── Prompt 内容 (与 summarize-expert/scripts/prompt_topics.md 的 ## Prompt 段保持一致) ──
SYSTEM_PROMPT = """你是文章拆解助手。任务：把用户提供的文本（文章/视频转录/播客/任何长内容）拆成结构化总结，让用户完全不用读原文就能掌握全文脉络。

## 输出 JSON 结构（严格遵守，不要任何额外字段、不要 Markdown 包装）
{
  "summary": "一句话总结（≤80字）",
  "topics": [
    [["<emoji>", "<主题标题>"], ["<bullet>", "<bullet>", "<bullet>"]],
    [["<emoji>", "<主题标题>"], ["<bullet>", "<bullet>"]]
  ]
}

## 核心规则

1. **零格式噪声**
   - 禁止任何导览前缀（"00%-25%"、"第一段"、"接下来"、"[导览]" 等）
   - 禁止时间戳、置信度分数、"原文提到"、"作者认为" 等空话开头
   - bullet 直接说内容，不要 "本文认为..."、"该文指出..." 等元描述

2. **覆盖度优先**
   - 原文每个具体信息都要进总结。漏掉细节比冗余更严重
   - 必须保留：数字（百分比/金额/时间）、专有名词（产品/人名/公司）、对比关系（"A 比 B"、"除 X 外都 Y"）、因果链（"因为...所以..."）
   - 抽象归纳降到最低。禁止把多个具体点压缩成"市场存在风险"这种空话
   - 可以压缩口语化重复（"这个"、"那个"、"就是说" 等口头禅剔除），但具体论点不丢

3. **主题先行的层级结构**
   - 把全文拆成 3-5 个主题板块（按逻辑主线，不是按原文顺序）
   - 每个主题用一句"主题句"作标题（13 字以内最佳；超 13 字截断到 13 字保留核心）
   - 主题下 bullet 列原文具体内容
   - 主题排列顺序按原文逻辑递进（先因后果/先现状后预测/先问题后方案）

4. **emoji 选主题类型（按主题情绪/领域选，不是装饰）**
   - 💹 金融/价格/交易 | 📈 上涨/增长/扩张 | 📉 下跌/风险/收缩
   - 🔒 监管/约束/规则 | 🏛 政策/制度 | ⚖️ 法律/合规/对比
   - 💡 核心观点/结论 | 🎯 行动/策略 | 🛠 方法/技巧
   - ⚠️ 警告/警示 | 📊 数据/统计 | 🔍 观察/分析
   - 🌐 国际/全球 | 🇨🇳🇺🇸🇰🇷🇯🇵 国家/地区
   - 🏢 公司/企业 | 🤖 AI/技术/产品
   - 📚 知识/教育 | 🧠 思维/方法论
   - 其他场景选最接近的一个，不要混用

5. **bullet 句式（重要）**
   - 每条 bullet 是完整的具体事实，不是抽象标签
   - ✅ "杠杆ETF会放大市场波动、加剧市场集中、影响企业发展、强化单边资金流"
   - ❌ "指出市场风险问题"
   - 一条 bullet 一个事实点。如果原文一段连讲 4 个事实，拆成 4 条 bullet

6. **不发明内容**
   - 只总结原文已有的信息
   - 不补充原文没有的背景知识
   - 不做主观评价（"我觉得"、"这说明..." 等）
   - 不预测未说的结论

## 输出要求

- 主题板块数：3-5 个（少则拆不够，多则碎片化）
- 每个主题下 bullet 数：2-5 条
- summary：≤80 字，抓全文核心判断
- 语气：客观平实，不评价不抒情
- 输出语言：与原文语言一致（中文原文输出中文）

## 严格执行

- 输出必须是合法 JSON，可被 json.loads() 解析
- 不要输出 JSON 以外的任何内容（不要解释、不要"以下是..."、不要 markdown 包裹）
- 字段命名严格：summary / topics，小写，复数 topics 不要写成 topic
- 主题标题是字符串（不含 emoji），emoji 单独字段
"""


def get_key():
    if not CRED.exists():
        print(f"❌ 未找到凭证: {CRED}", file=sys.stderr)
        return None
    try:
        return json.loads(CRED.read_text()).get("api_key", "")
    except Exception as e:
        print(f"❌ 凭证读取失败: {e}", file=sys.stderr)
        return None


def strip_frontmatter(text):
    """去掉 --- frontmatter --- 段"""
    if text.startswith("---"):
        m = re.search(r"^---\n.*?\n---\n", text, re.S)
        if m:
            return text[m.end():].strip()
    return text.strip()


def call_glm(system, user_content, api_key):
    """调用 GLM-4-flash。异常由调用方 catch 后走 fallback 引擎。"""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
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



# ════════════════════════════════════════════════════════════════════════════════
# 2026-07-20: bailian text API (OpenAI 兼容, dashscope base_url)
# 给 worker 池用: 可以与 glm 叠加并发作为 fallback / 主路径
# 默认 model=qwen3.5-flash (advisor 推荐: 1M 上下文 + native JSON + cost-optimized)
# ════════════════════════════════════════════════════════════════════════════════

BAILIAN_TEXT_DEFAULT_MODEL = "qwen3.5-flash"

# ── Bailian 配额缓存（预爬取时写入，summarize_text 读，不每次调 CLI）─────────────
_STATE_FILE = Path(__file__).parent.parent / "state" / "bailian_quota.json"

def _get_cached_best_model() -> str:
    """从爬取前缓存的 bailian_quota.json 读最佳可用模型。
    无缓存或解析失败时回退 BAILIAN_TEXT_DEFAULT_MODEL。
    """
    try:
        data = json.loads(_STATE_FILE.read_text())
        best = data.get("best_model")
        if best and data["models"].get(best, {}).get("available"):
            return best
    except Exception:
        pass
    return BAILIAN_TEXT_DEFAULT_MODEL

# 复用 _bailian_run 样式: subprocess + start_new_session (2026-07-21: 不再剥 HTTPS_PROXY)
# bl CLI 内部处理 auth (工作区 token / access_token), 不需要单独读 api_key.
import subprocess as _subprocess_bailian
_BAILIAN_BIN_LOCAL = shutil.which("bl") or shutil.which("bailian") or str(Path.home() / ".npm-global" / "bin" / "bailian")


def _bailian_text_run(cmd, timeout):
    """子进程执行器 (start_new_session + killpg 解决 bl Node.js fork 子进程不占 pipe EOF).
    2026-07-21: 不再剥 HTTPS_PROXY — VPN 按域名自动路由, 代码层不干预.
    """
    proc = _subprocess_bailian.Popen(
        cmd,
        stdout=_subprocess_bailian.PIPE,
        stderr=_subprocess_bailian.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return stdout or "", stderr or "", proc.returncode
    except _subprocess_bailian.TimeoutExpired:
        try:
            _os.killpg(_os.getpgid(proc.pid), 9)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.communicate(timeout=2)
        except Exception:
            pass
        raise


def call_bailian_text(system, user_content, model=None, timeout=180, max_tokens=None, temperature=None):
    """bailian 文本模型调用 (绕走 bl CLI, 不需额外凭证).

    Args:
        system: system prompt
        user_content: user 消息 (不含 frontmatter 的正文)
        model: 默认 qwen3.5-flash; 可选 qwen3.5-flash-2026-02-23, qwen-plus-latest
        timeout: 请求超时 (秒)
        max_tokens: 默认 MAX_TOKENS
        temperature: 默认 TEMPERATURE
    Returns:
        LLM 返回的文本 (需自己 parse_json_strict)
    """
    model = model or BAILIAN_TEXT_DEFAULT_MODEL
    cmd = [
        _BAILIAN_BIN_LOCAL, "text", "chat",
        "--model", model,
        "--system", system,
        "--message", user_content,
        "--max-tokens", str(max_tokens or MAX_TOKENS),
        "--temperature", str(temperature if temperature is not None else TEMPERATURE),
        "--no-stream" if "--no-stream" in _get_bl_flags() else "--quiet",
    ]
    # 简化: 不加 --no-stream (默认静默输出), 使用 --output text 以保证干净
    cmd = [
        _BAILIAN_BIN_LOCAL, "text", "chat",
        "--model", model,
        "--system", system,
        "--message", user_content,
        "--max-tokens", str(max_tokens or MAX_TOKENS),
        "--temperature", str(temperature if temperature is not None else TEMPERATURE),
        "--quiet",
    ]
    try:
        stdout, stderr, rc = _bailian_text_run(cmd, timeout=timeout)
    except _subprocess_bailian.TimeoutExpired:
        raise RuntimeError(f"bailian text 超时 {timeout}s")
    if rc != 0:
        raise RuntimeError(f"bailian text rc={rc}: {(stderr or stdout)[:200]}")

    return stdout

# ── MiniMax 文本模型（第三兜底，无配额限制）─────────────────────────────────────
_MMX_BIN = shutil.which("mmx")
_MINIMAX_DEFAULT_MODEL = "MiniMax-M2.7"

def call_minimax_text(system, user_content, model=None, timeout=180):
    """MiniMax 文本模型（第三兜底，不查配额，永远可用）。"""
    import subprocess as _sub_mmx
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
    proc = _sub_mmx.Popen(
        cmd,
        stdout=_sub_mmx.PIPE,
        stderr=_sub_mmx.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except _sub_mmx.TimeoutExpired:
        try:
            _os.killpg(_os.getpgid(proc.pid), 9)
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
    return (stdout or "").strip()


def _get_bl_flags():
    """检查 bl CLI 是否支持 --no-stream (默认返回 None, 调用者忽略).
    预留接口, 以防 bl 版本变化需要动态适配.
    """
    try:
        out = _subprocess_bailian.run(
            [_BAILIAN_BIN_LOCAL, "text", "chat", "--help"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.split()
    except Exception:
        return []


def parse_json_strict(text):
    """从 LLM 输出里抠 JSON（容错：去掉 markdown 包裹/前后杂字）"""
    s = text.strip()
    # 去掉 ```json ... ``` 包裹
    m = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", s, re.S)
    if m:
        s = m.group(1).strip()
    # 找第一个 { 到最后一个 }
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end > start:
        s = s[start : end + 1]
    return json.loads(s)


def normalize_topics(topics):
    """LLM 输出的 topics 形状可能不规范, 容错修复为 [[emoji,title], [bullets]] 标准形。

    失败模式:
    - 嵌套过深: [[[emoji,title,b1,b2], [...]]] — 整层扁平化
    - 嵌套太浅: [[emoji, title, b1, b2]] — 拆成 [[emoji,title], [b1, b2]]
    - 标准: [[[emoji, title], [b1, b2]]] — 不动

    启发式:
    - 第一个元素是 str 且长度 ≤4 (含 emoji) → 视为 emoji
    - 第二个元素是 str 且 ≥1 字 → 视为 title
    - 剩余 string 元素 → 视为 bullets
    """
    fixed = []
    for t in topics:
        if not isinstance(t, list):
            continue
        # 拍平所有嵌套 list 直到元素全是 str
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
        # flat[0] = emoji, flat[1] = title, flat[2:] = bullets
        emoji, title = flat[0], flat[1]
        bullets = flat[2:]
        # 截断 title
        if len(title) > 13:
            title = title[:13]
        # 过滤空 bullet
        bullets = [b.strip() for b in bullets if b and b.strip()]
        if bullets:
            fixed.append([[emoji, title], bullets])
    return fixed


def validate(obj):
    """校验 JSON 结构是否合规。失败抛 ValueError。"""
    if not isinstance(obj, dict):
        raise ValueError("顶层不是 dict")
    if not isinstance(obj.get("summary"), str) or not obj["summary"].strip():
        raise ValueError("summary 缺失/非字符串")
    if len(obj["summary"]) > 200:
        # 封顶到 200 字 (原 [:80] 会破坏性截断大部分内容, 已修正)
        obj["summary"] = obj["summary"][:200]
    topics = obj.get("topics")
    if not isinstance(topics, list) or len(topics) < 2:
        raise ValueError(f"topics 应为 ≥2 个主题, 实际 {type(topics).__name__}({len(topics) if isinstance(topics, list) else '?'})")
    # 先尝试 normalize（容错 LLM 输出不规范）
    topics = normalize_topics(topics)
    if len(topics) < 2:
        raise ValueError(f"normalize 后 topics 不足 2 个: {len(topics)}")
    if len(topics) > 5:
        topics = topics[:5]
    for i, t in enumerate(topics):
        if not isinstance(t, list) or len(t) != 2:
            raise ValueError(f"topic[{i}] 应为 2 元素 list, 实际 {t}")
        title_emoji, bullets = t
        if not isinstance(title_emoji, list) or len(title_emoji) != 2:
            raise ValueError(f"topic[{i}].title_emoji 应为 [emoji, title] 2 元 list")
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


def summarize_text(body_text, engine="auto", model=None, min_chars=100, max_body=None):
    """worker 友好的文本调用层: 只接受正文文本, 不拆 md / frontmatter.

    Args:
        body_text: 正文文本 (不含 frontmatter)
        engine: "glm" | "bailian" | "auto" (auto = glm 主, bailian 备选)
        model: 当 engine="bailian" 时生效, 默认 qwen3.5-flash
        min_chars: 正文最小长度, 低于此不总结
        max_body: 最大输入长度, 默认 MAX_BODY

    Returns:
        dict {"summary": str, "topics": [[emoji, title], [bullets]]}
    """
    body = (body_text or "").strip()
    if len(body) < min_chars:
        raise RuntimeError(f"正文仅 {len(body)} 字符 (<{min_chars}), 跳过总结")
    user = body[:max_body or MAX_BODY]
    last_err = None
    engines = ["glm", "bailian", "minimax"] if engine == "auto" else [engine]
    for eng in engines:
        try:
            if eng == "glm":
                api_key = get_key()
                if not api_key:
                    raise RuntimeError("无 GLM API key")
                raw = call_glm(SYSTEM_PROMPT, user, api_key)
            elif eng == "bailian":
                bailian_model = model or _get_cached_best_model()
                raw = call_bailian_text(SYSTEM_PROMPT, user, model=bailian_model)
            elif eng == "minimax":
                raw = call_minimax_text(SYSTEM_PROMPT, user)
            else:
                raise RuntimeError(f"未知引擎: {eng}")
            obj = parse_json_strict(raw)
            obj = validate(obj)
            obj["engine"] = eng
            return obj
        except Exception as e:
            last_err = e
            print(f"  [summarize] engine={eng} 失败: {e}", flush=True)
            continue
    raise RuntimeError(f"总结失败 (所有引擎): {last_err}")


def summarize(md_path):
    """向后兼容入口: 读 md → 拆 frontmatter → 调 summarize_text.
    保持原有签名, caller 不变.
    """
    api_key = get_key()
    if not api_key:
        raise RuntimeError("无 API key")

    md = Path(md_path).read_text(encoding="utf-8")
    body = strip_frontmatter(md)
    if len(body) < 100:
        raise RuntimeError(f"正文仅 {len(body)} 字符 (<100), 跳过总结")
    return summarize_text(body, engine="auto")


def main():
    if len(sys.argv) < 2:
        print("用法: summarize.py <md_path>", file=sys.stderr)
        sys.exit(1)
    try:
        obj = summarize(sys.argv[1])
        # 输出纯 JSON 到 stdout（便于 shell 捕获）
        sys.stdout.write(json.dumps(obj, ensure_ascii=False))
        sys.stdout.flush()
    except Exception as e:
        sys.stderr.write(f"❌ {e}\n")
        sys.exit(2)


if __name__ == "__main__":
    main()

def _format_summary_section(obj):
    """从 summarize() 返回值构造一段 markdown 文本 (`## 总结` + 🎯/⏳/💡 标签).
    供 inject_summary_to_md / migrate_summary_to_abstract 共用.
    """
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


def inject_summary_to_md(md_path, obj, overwrite=False):
    """把 LLM 生成的 {summary, topics} 写到 md 文件 abstract 区域
    (frontmatter 之后, 第一个 ## 之前).

    为什么是 abstract 区域: common/summarize_markdown.build_note_block() 只从
    abstract 区域抠 🎯/⏳/💡 标签 (parse_abstract), 写到末尾的总结会被
    transcript 截断屏蔽, 推飞书时拿不到 core/speedread/quotes.

    写入位置示意:
      ---
      frontmatter
      ---
      <abstract 内容>
      ## 总结           ← 写在这里
      🎯 ...
      ⏳ ...
      💡 ...
      ## 转录 / ## 描述 / ## 第一个H2   ← 这里及之后是 transcript 区域, 保持不动
      ...
    """
    p = Path(md_path)
    text = p.read_text(encoding="utf-8")

    # 先清理掉任何位置 (末尾) 已有的 ## 总结 段 (避免重复)
    text = _strip_summary_section(text)

    # 切 frontmatter
    frontmatter = ""
    body = text
    if body.startswith("---"):
        m = re.search(r"^---\n.*?\n---\n", body, re.S)
        if m:
            frontmatter = body[:m.end()]
            body = body[m.end():]
    # 切 abstract (到第一个 ##)
    first_h2 = re.search(r"^##\s", body, re.MULTILINE)
    if first_h2:
        abstract = body[:first_h2.start()].rstrip()
        rest = body[first_h2.start():]
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


def _strip_summary_section(text):
    """从 md 文本里剥离任何位置 (一般是末尾) 的 ## 总结 段.
    段定义: '## 总结' 起到下一个 '## ' 标题前, 或文末.
    """
    return re.sub(r"\n+## 总结\s*\n[\s\S]*?(?=\n## |\Z)", "", text)


def migrate_summary_to_abstract(md_path):
    """一次性迁移: 把误写在末尾的 ## 总结 段挪到 abstract 区域.
    适用于之前 inject_summary_to_md 写入位置错误时批量修正.

    Returns: bool - 是否做了迁移.
    """
    p = Path(md_path)
    text = p.read_text(encoding="utf-8")
    # 提取末尾的 ## 总结 段
    m = re.search(r"\n+## 总结\s*\n([\s\S]*?)(?=\n## |\Z)", text)
    if not m:
        return False
    summary_body = m.group(1).strip()
    stripped = text[:m.start()].rstrip() + "\n"
    # 写回: abstract 区域
    if stripped.startswith("---"):
        fm = re.search(r"^---\n.*?\n---\n", stripped, re.S)
        if fm:
            frontmatter = stripped[:fm.end()]
            body = stripped[fm.end():]
        else:
            frontmatter = ""
            body = stripped
    else:
        frontmatter = ""
        body = stripped
    first_h2 = re.search(r"^##\s", body, re.MULTILINE)
    if first_h2:
        abstract = body[:first_h2.start()].rstrip()
        rest = body[first_h2.start():]
    else:
        abstract = body.rstrip()
        rest = ""
    if re.search(r"^##\s*总结\s*$", abstract, re.M):
        return False
    sep = "\n\n" if abstract else ""
    new_body = abstract + sep + "## 总结\n\n" + summary_body + "\n\n" + rest.lstrip()
    p.write_text(frontmatter + new_body, encoding="utf-8")
    return True


def has_summary_section(md_path):
    """md 文件是否含 `## 总结` 段.

    兼容两种位置 (2026-08-07 修 #24):
    1. abstract 区域内 (frontmatter 之后, 第一个 H2 之前) 含 `## 总结` 段
    2. 第一个 H2 本身标题就是 `总结` (abstract 为空的情况, 如抖音爬取的 md)

    原 bug: 只看 abstract 区域, 当 abstract 为空 + 第一个 H2 就是 `## 总结`
    时返回 False, 误判 "缺总结", 导致 backfill_summary 重复补。
    """
    p = Path(md_path)
    if not p.exists():
        return False
    text = p.read_text(encoding="utf-8")
    # 切 frontmatter
    if text.startswith("---"):
        m = re.search(r"^---\n.*?\n---\n", text, re.S)
        if m:
            text = text[m.end():]
    # 找第一个 H2
    first_h2 = re.search(r"^##\s*(.+)$", text, re.MULTILINE)
    if not first_h2:
        return False
    # 检查 1: 第一个 H2 本身就是 `## 总结`
    if first_h2.group(1).strip() == "总结":
        return True
    # 检查 2: abstract 区域 (第一个 H2 之前) 含 `## 总结` 段
    abstract = text[:first_h2.start()]
    return bool(re.search(r"^##\s*总结\s*$", abstract, re.M))



