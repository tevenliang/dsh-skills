#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
recovery.py — 恢复决策引擎
根据 patterns.scan_line() 匹配到的异常，执行对应的恢复动作。
"""
import time, threading
from datetime import datetime, timezone, timedelta
from common_supervisor.patterns import scan_line, scan_lines, MatchResult, Severity
from common_supervisor.state import (
    load_recovery, save_recovery,
    disable_provider, set_provider_cooldown, set_mlx_degraded, set_glm_backoff,
    restart_opencli, record_provider_switch, record_error,
    load_timing, save_timing, update_status,
    RECOVERY_PATH,
)

TZ = timezone(timedelta(hours=8))
_lock = threading.Lock()

# Groq 连续失败计数（进程内持久化）
_groq_fail_count = 0
_glm_fail_count = 0
_mlx_fail_count = 0

# MLX 性能降级阈值
MLX_RTF_THRESHOLD = 0.5   # RTF 超过此值视为性能异常
MLX_DURATION_THRESHOLD = 300  # 单条超过 300s 视为卡死


def react(line: str) -> str | None:
    """
    分析一行子进程输出，返回干预描述（无干预则 None）。
    幂等：同类错误重复出现时累加计数，超过阈值才降级。
    """
    global _groq_fail_count, _glm_fail_count, _mlx_fail_count

    with _lock:
        match = scan_line(line)
        if not match:
            return None

        action = None

        # ── Groq 成功：连续失败归零，并清理 supervisor cooldown ──────────
        if match.pattern_key == "groq_success":
            _groq_fail_count = 0
            rec = load_recovery()
            if rec.get("groq", {}).get("status") == "cooldown":
                rec["groq"] = {"status": "active"}
                save_recovery(rec)
                update_status(provider_states=rec.copy())
            return None

        # ── Groq 401（永久禁用）──────────────────────────────────────────
        if match.pattern_key == "groq_401":
            # 修 #3: 已经 disabled 的不再累加, 但也不要在 raw_line 嵌入之前 reason
            rec = load_recovery().get("groq", {})
            already = rec.get("status") == "disabled" and "401" in str(rec.get("disabled_reason", ""))
            if not already:
                disable_provider("groq", f"Groq 401 invalid_api_key: {match.matched_text[:80]}")
                update_status(provider_states=load_recovery().copy())
            action = "Groq 401 invalid key, 已禁用 Groq (Groq only, 无 fallback)"
            _groq_fail_count = 0
            return action

        # ── Groq 429（冷却后重试）────────────────────────────────────────
        # 修 #3 (2026-07-30): groq_success 日志会清零连续失败计数；这里只累加真实失败。
        #                    单次 cooldown 60s→120s，减少连续触发。
        # 修 #3b: 第二次 429 触发 cooldown 5min 时, reason 截断, 避免日志嵌入.
        if match.pattern_key == "groq_429":
            _groq_fail_count += 1
            if _groq_fail_count >= 2:
                set_provider_cooldown("groq", 300, "连续 429 (>=2)")
                update_status(provider_states=load_recovery().copy())
                action = "Groq 429 x2, Groq 冷却 5min (Groq only, 无 fallback)"
                _groq_fail_count = 0
            else:
                # 修 #3: 单次 429 cooldown 60s → 120s, 给限流窗口更多恢复时间
                set_provider_cooldown("groq", 120, "单次 429")
                action = "Groq 429, 等待 2min 后重试"
            return action

        # ── Groq 超时（重试 1 次，失败禁用 Groq, Groq only）─────────────────────────
        if match.pattern_key == "groq_timeout":
            _groq_fail_count += 1
            if _groq_fail_count >= 2:
                disable_provider("groq", f"Groq 超时 x2: {match.raw_line[:100]}")
                update_status(provider_states=load_recovery().copy())
                action = "Groq 超时 x2，禁用 Groq (Groq only, 无 fallback)"
                _groq_fail_count = 0
            else:
                action = "Groq 超时，第 1 次，稍后重试"
            return action

        # ── Groq 连接错误（同上）──────────────────────────────────────────
        if match.pattern_key == "groq_conn":
            _groq_fail_count += 1
            if _groq_fail_count >= 2:
                disable_provider("groq", f"Groq 连接错误: {match.raw_line[:100]}")
                update_status(provider_states=load_recovery().copy())
                action = "Groq 连接错误 x2，禁用 Groq (Groq only, 无 fallback)"
                _groq_fail_count = 0
            else:
                action = "Groq 连接错误，等待后重试"
            return action

        # ── Bailian 团队授权失效（去重：已被禁就不再 record）───────────
        if match.pattern_key == "bailian_team_auth":
            rec = load_recovery().get("bailian", {})
            already_disabled = rec.get("status") == "disabled" and "NotAuthorised" in str(rec.get("disabled_reason", ""))
            if not already_disabled:
                disable_provider("bailian", f"BailianGateway.Team.NotAuthorised: {match.raw_line[:120]}")
                record_provider_switch("bailian", "mlx", "BailianGateway.Team.NotAuthorised")
                update_status(provider_states=load_recovery().copy())
            action = "Bailian 团队授权失效 (NotAuthorised)，禁用 Bailian，切 MLX"
            return action

        # ── Bailian 额度耗尽（去重 + 防递归）───────────────────────────────
        # 修 #4 (2026-07-30): patterns.py 已用 negative lookahead 排除 '⏭️ 跳过 (recovery: ...)' 行
        # 但 raw_line 仍可能包含 '额度耗尽' (来自真实 bailian 错误), 这里二次去重:
        #   - 如果当前 reason 已经 disable, 直接 return 不写新 reason
        #   - reason 只保留 'Bailian 额度耗尽' 前缀, 不再嵌入 raw_line
        if match.pattern_key == "bailian_quota":
            rec = load_recovery().get("bailian", {})
            already_disabled = rec.get("status") == "disabled" and "额度耗尽" in str(rec.get("disabled_reason", ""))
            if not already_disabled:
                # 用纯标签, 不嵌入 raw_line, 避免 'recovery 关键词在 disabled_reason 里再触发新匹配'
                disable_provider("bailian", "Bailian 额度耗尽")
                record_provider_switch("bailian", "mlx", "Bailian 额度耗尽")
                update_status(provider_states=load_recovery().copy())
            action = "Bailian 额度耗尽, 禁用 Bailian, 切 MLX (已禁用不再记录)"
            return action

        # ── Bailian 500/服务端错误（等 30s 重试）──────────────────────────
        if match.pattern_key == "bailian_500":
            set_provider_cooldown("bailian", 30, "Bailian 500")
            action = "Bailian 500，等待 30s 后重试"
            return action

        # ── Bailian poll 超时（降级切 MLX，去重）───────────────────────────
        if match.pattern_key == "bailian_poll_timeout":
            rec = load_recovery().get("bailian", {})
            already_disabled = rec.get("status") == "disabled" and "poll 超时" in str(rec.get("disabled_reason", ""))
            if not already_disabled:
                disable_provider("bailian", f"Bailian poll 超时: {match.raw_line[:100]}")
                record_provider_switch("bailian", "mlx", "Bailian poll 超时")
                update_status(provider_states=load_recovery().copy())
            action = "Bailian poll 超时，禁用 Bailian，切 MLX"
            return action

        # ── MLX RTF 异常 ─────────────────────────────────────────────────
        if match.pattern_key == "mlx_rtf" and match.rtf is not None:
            if match.rtf > MLX_RTF_THRESHOLD:
                # 性能异常：降级 MLX 超时限制 (Groq only, 不切 Bailian)
                set_mlx_degraded(timeout_sec=180)
                action = f"MLX RTF={match.rtf}x 异常，降级 MLX（超时 180s）(Groq only, 无 fallback)"
            return action

        # ── MLX 耗时超 5 分钟 ────────────────────────────────────────────
        if match.pattern_key == "mlx_duration" and match.duration_sec is not None:
            if match.duration_sec > MLX_DURATION_THRESHOLD:
                _mlx_fail_count += 1
                if _mlx_fail_count >= 2:
                    disable_provider("mlx", f"MLX 单条耗时 {match.duration_sec}s x2")
                    record_provider_switch("mlx", "bailian", f"MLX 耗时超限 x2 ({match.duration_sec}s)")
                    update_status(provider_states=load_recovery().copy())
                    action = f"MLX 耗时 {match.duration_sec}s x2，禁用 MLX (Groq only, 无 fallback)"
                    _mlx_fail_count = 0
                else:
                    set_mlx_degraded(timeout_sec=180)
                    action = f"MLX 耗时 {match.duration_sec}s，降级 MLX 超时 180s"
            return action

        # ── MLX 报错 ─────────────────────────────────────────────────────
        if match.pattern_key == "mlx_error":
            _mlx_fail_count += 1
            if _mlx_fail_count >= 2:
                disable_provider("mlx", f"MLX 错误: {match.raw_line[:100]}")
                record_provider_switch("mlx", "bailian", "MLX 错误 x2")
                update_status(provider_states=load_recovery().copy())
                action = "MLX 错误 x2，禁用 MLX (Groq only, 无 fallback)"
                _mlx_fail_count = 0
            else:
                action = "MLX 错误，等待后重试"
            return action

        # ── GLM 429（指数退避）───────────────────────────────────────────
        if match.pattern_key == "glm_429":
            _glm_fail_count += 1
            # 指数退避：第1次 60s，第2次 120s，第3次+ 300s
            backoff = min(300, 60 * (2 ** (_glm_fail_count - 1)))
            set_glm_backoff(backoff, f"GLM 429 x{_glm_fail_count}")
            action = f"GLM 429 x{_glm_fail_count}，退避 {backoff}s"
            return action

        # ── GLM 超时（重试 1 次，失败跳过）───────────────────────────────
        if match.pattern_key == "glm_timeout":
            _glm_fail_count += 1
            if _glm_fail_count >= 2:
                record_error("glm_summary", f"GLM 超时 x2，跳过该条总结: {match.raw_line[:100]}", "MED")
                action = "GLM 超时 x2，跳过该条总结，继续后续"
                _glm_fail_count = 0
            else:
                action = "GLM 超时，第 1 次，稍后重试"
            return action

        # ── GLM 连接错误 ─────────────────────────────────────────────────
        if match.pattern_key == "glm_conn":
            _glm_fail_count += 1
            if _glm_fail_count >= 2:
                record_error("glm_summary", f"GLM 连接错误 x2，跳过总结: {match.raw_line[:100]}", "MED")
                action = "GLM 连接错误 x2，跳过该条总结，继续后续"
                _glm_fail_count = 0
            else:
                action = "GLM 连接错误，等待后重试"
            return action

        # ── opencli 断连 ─────────────────────────────────────────────────
        if match.pattern_key == "opencli_disconnect":
            restart_opencli()
            action = "opencli daemon 断连，重启 daemon"
            return action

        # ── opencli 超时（重试 1 次）─────────────────────────────────────
        if match.pattern_key == "opencli_timeout":
            restart_opencli()
            action = "opencli 超时，重启 daemon"
            return action

        # ── B站 -412（IP 被封）───────────────────────────────────────────
        if match.pattern_key == "bili_412":
            record_error("fetch_bilibili", "B站 -412 IP被封，等待 5min", "MED")
            set_provider_cooldown("bili", 300, "B站 -412")
            action = "B站 -412（IP 被封），等待 5min 后继续"
            return action

        # ── watchodg kill（进程已卡死很久）────────────────────────────────
        if match.pattern_key == "watchdog_kill":
            record_error("subprocess", "watchdog 已触发 dump，可能是子进程卡死", "HIGH")
            action = "⚠️ watchdog dump 栈，子进程可能已卡死"
            return action

        # ── 子进程异常退出码 ─────────────────────────────────────────────
        if match.pattern_key == "proc_nonzero_exit":
            record_error("subprocess", f"子进程异常退出: {match.raw_line}", "HIGH")
            action = f"❌ 子进程退出码异常: {match.raw_line[:100]}"
            return action

        return None


def react_lines(lines: list[str]) -> list[str]:
    """扫描多行，返回所有干预描述列表。"""
    actions = []
    for line in lines:
        a = react(line)
        if a:
            actions.append(a)
    return actions


def reset_counts():
    """每次新流程开始时重置计数器。"""
    global _groq_fail_count, _glm_fail_count, _mlx_fail_count
    _groq_fail_count = 0
    _glm_fail_count = 0
    _mlx_fail_count = 0
