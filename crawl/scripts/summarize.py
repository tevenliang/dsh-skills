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
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"GLM HTTP {e.code}: {body}")
    except Exception as e:
        raise RuntimeError(f"GLM 调用异常: {e}")

    choices = result.get("choices") or []
    if not choices:
        raise RuntimeError(f"GLM 无 choices: {json.dumps(result)[:200]}")
    return choices[0].get("message", {}).get("content", "")


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
        obj["summary"] = obj["summary"][:80]
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


def summarize(md_path):
    api_key = get_key()
    if not api_key:
        raise RuntimeError("无 API key")

    md = Path(md_path).read_text(encoding="utf-8")
    body = strip_frontmatter(md)
    if len(body) < 100:
        # 太短不总结（避免 LLM 编造）
        raise RuntimeError(f"正文仅 {len(body)} 字符 (<100), 跳过总结")

    user = body[:MAX_BODY]
    last_err = None
    for attempt in range(2):
        try:
            raw = call_glm(SYSTEM_PROMPT, user, api_key)
            obj = parse_json_strict(raw)
            obj = validate(obj)
            return obj
        except Exception as e:
            last_err = e
            # 第二次失败不再 retry
    raise RuntimeError(f"总结失败（重试 1 次后）: {last_err}")


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