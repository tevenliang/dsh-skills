#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patterns.py — 异常模式识别规则
Supervisor 实时扫描子进程 stdout，每行匹配以下模式，
匹配后返回 (action, severity, detail) 三元组供 recovery.py 决策。
"""
import re
from dataclasses import dataclass
from enum import IntEnum

class Severity(IntEnum):
    LOW    = 1   # 记录日志，继续观察
    MED    = 2   # 触发退避/重试策略
    HIGH   = 3   # 立即降级/切换 provider
    CRIT   = 4   # 立即终止子进程，重启

# ── Groq 异常 ─────────────────────────────────────────────────────────────────
GROQ_PATTERNS = [
    (re.compile(r'\[groq\](?![^\n]*?(?:⏭️\s*跳过|recovery:))[^\n]*?(?:401|invalid_api_key)', re.I),            Severity.CRIT,  "groq_401"),
    # 修 #1: 同样避免匹配自生成的 ⏭️ 跳过行
    (re.compile(r'\[groq\](?![^\n]*?(?:⏭️\s*跳过|recovery:))[^\n]*?(?:429|rate\.limit|Too\s+Many\s+Requests)', re.I), Severity.MED,  "groq_429"),
    (re.compile(r'\[groq\](?![^\n]*?(?:⏭️\s*跳过|recovery:))[^\n]*?(?:timeout)', re.I),              Severity.MED,  "groq_timeout"),
    (re.compile(r'\[groq\](?![^\n]*?(?:⏭️\s*跳过|recovery:))[^\n]*?(?:connection|ConnectionError|ECONNREFUSED)', re.I), Severity.MED, "groq_conn"),
    # 成功行用于清理 supervisor 内连续失败计数和过期 cooldown 状态
    (re.compile(r'\[groq\][^\n]*?成功\s+\d+\s+chars', re.I), Severity.LOW, "groq_success"),
]

# ── Bailian 异常 ──────────────────────────────────────────────────────────────
BAILIAN_PATTERNS = [
    # 团队授权失效 (BailianGateway.Team.NotAuthorised) —— 不是额度耗尽
    (re.compile(r'\[bailian\](?![^\n]*?(?:⏭️\s*跳过|recovery:))[^\n]*?(?:NotAuthorised|Team\.NotAuthorised)', re.I), Severity.CRIT, "bailian_team_auth"),
    # 额度耗尽 (403 FreeTierOnly / quota exhausted)
    # 修 #1 (2026-07-30): 用 negative lookahead 排除自生成的 '⏭️  跳过 (recovery: ...)' 行, 避免 supervisor 递归 disable
    (re.compile(r'\[bailian\](?![^\n]*?(?:⏭️\s*跳过|recovery:))[^\n]*?(?:403.*free|freetieronly|quota|exhaust|额度.{0,4}耗尽)', re.I), Severity.CRIT, "bailian_quota"),
    # 服务端错误
    (re.compile(r'\[bailian\](?![^\n]*?(?:⏭️\s*跳过|recovery:))[^\n]*?(?:500|InternalServerError)', re.I), Severity.MED, "bailian_500"),
    # 超时（poll 多次后仍 processing）
    (re.compile(r'\[bailian\](?![^\n]*?(?:⏭️\s*跳过|recovery:))[^\n]*?(?:poll.*timeout|软超时)', re.I), Severity.MED, "bailian_poll_timeout"),
]

# ── MLX 异常 ─────────────────────────────────────────────────────────────────
# 性能异常：RTF > 0.5（1分钟音频需要 >30s 推理，接近实时极限）
# 严重性能问题：RTF > 1.0（推理比实时慢）
MLX_PATTERNS = [
    # RTF 超阈值 (e.g. RTF=0.62x, RTF=1.23x)
    (re.compile(r'RTF=(\d+\.?\d*)x', re.I), Severity.MED, "mlx_rtf"),
    # MLX 单条耗时超 5 分钟（300s）
    (re.compile(r'\[mlx\](?![^\n]*?(?:⏭️\s*跳过|recovery:))[^\n]*?(\d+)m(\d+)s', re.I), Severity.MED, "mlx_duration"),
    # MLX 报错
    (re.compile(r'\[mlx\](?![^\n]*?(?:⏭️\s*跳过|recovery:))[^\n]*?error|MLX(?![^\n]*?(?:⏭️\s*跳过|recovery:))[^\n]*?failed', re.I), Severity.HIGH, "mlx_error"),
]

# ── GLM 总结异常 ──────────────────────────────────────────────────────────────
GLM_PATTERNS = [
    # 429 限速
    (re.compile(r'\[glm\](?![^\n]*?(?:⏭️\s*跳过|recovery:))[^\n]*?(?:429|rate\.limit|Too\s+Many\s+Requests)', re.I), Severity.MED, "glm_429"),
    # 超时
    (re.compile(r'\[glm\](?![^\n]*?(?:⏭️\s*跳过|recovery:))[^\n]*?(?:timeout|超时)', re.I), Severity.MED, "glm_timeout"),
    # 连接错误
    (re.compile(r'\[glm\](?![^\n]*?(?:⏭️\s*跳过|recovery:))[^\n]*?(?:connection|ConnectionError|ECONNREFUSED)', re.I), Severity.MED, "glm_conn"),
    # 模型不支持等业务错误
    (re.compile(r'\[glm\](?![^\n]*?(?:⏭️\s*跳过|recovery:))[^\n]*?(?:400|invalid.*request|bad.*request)', re.I), Severity.MED, "glm_400"),
]

# ── opencli 异常 ──────────────────────────────────────────────────────────────
OPENCLI_PATTERNS = [
    # daemon 断连
    (re.compile(r'opencli.*disconnected|daemon.*disconnect|Extension.*not connected', re.I), Severity.MED, "opencli_disconnect"),
    # opencli 操作超时
    (re.compile(r'opencli.*timeout|tab.*timeout|select.*timeout', re.I), Severity.MED, "opencli_timeout"),
]

# ── 其他通用异常 ──────────────────────────────────────────────────────────────
OTHER_PATTERNS = [
    # 进程被 watchdog kill（说明已经卡死很久了）
    (re.compile(r'watchdog.*SIGTERM|watchdog.*dump', re.I), Severity.HIGH, "watchdog_kill"),
    # B站 -412（IP 被封）
    (re.compile(r'-412|IP.*blocked|IP.*封禁', re.I), Severity.MED, "bili_412"),
    # 子进程异常退出
    (re.compile(r'ProcessLookupError|SIGKILL|SIGTERM.*killpg', re.I), Severity.MED, "proc_killed"),
    # 未知异常退出码
    (re.compile(r'exited.*code.*[^0]', re.I), Severity.HIGH, "proc_nonzero_exit"),
]

# 合并所有 pattern（按优先级排序：CRIT > HIGH > MED > LOW）
ALL_PATTERNS = (
    GROQ_PATTERNS + BAILIAN_PATTERNS + MLX_PATTERNS +
    GLM_PATTERNS + OPENCLI_PATTERNS + OTHER_PATTERNS
)


@dataclass
class MatchResult:
    pattern_key: str   # e.g. "groq_401"
    severity: Severity
    raw_line: str      # 原始匹配行（截断到 200 字符）
    matched_text: str  # 匹配的文本片段

    # 额外解析（某些 pattern 需要提取数值）
    rtf: float | None = None          # MLX RTF 值
    duration_sec: int | None = None   # MLX 耗时（秒）


def scan_line(line: str) -> MatchResult | None:
    """扫描单行，返回 MatchResult 或 None。"""
    # Supervisor 自己生成的 provider skip 日志可能嵌入旧错误原文。
    # 必须整行短路；仅靠各 regex 的 lookahead 会从嵌套的第二个 [provider] 重新命中。
    if "recovery:" in line or "[recovery:skip]" in line or ("⏭️" in line and "跳过" in line):
        return None
    for pattern, severity, key in ALL_PATTERNS:
        m = pattern.search(line)
        if not m:
            continue
        matched_text = m.group(0)
        result = MatchResult(
            pattern_key=key,
            severity=severity,
            raw_line=line[:200],
            matched_text=matched_text,
        )

        # 额外解析：MLX RTF
        if key == "mlx_rtf":
            try:
                result.rtf = float(m.group(1))
            except (ValueError, IndexError):
                pass

        # 额外解析：MLX 耗时 mmss 格式
        if key == "mlx_duration":
            try:
                result.duration_sec = int(m.group(1)) * 60 + int(m.group(2))
            except (ValueError, IndexError):
                pass

        return result
    return None


def scan_lines(lines: list[str]) -> list[MatchResult]:
    """扫描多行，返回所有匹配结果。"""
    results = []
    for line in lines:
        r = scan_line(line)
        if r:
            results.append(r)
    return results
