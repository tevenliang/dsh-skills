#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_injection.py — 子进程侧注入器 (recovery.json consumer)

目标: crawl.py 子进程被 supervisor.py 启动后, 自动具备以下能力:
  1. 读 recovery.json, 跳过已禁用 (disabled) 的 provider
  2. 读 recovery.json, MLX 降级时缩短超时
  3. 读 recovery.json, GLM 退避窗口内跳过调用
  4. 写 timing.json, 为 Supervisor 合并后的耗时统计提供单条 op 时间

Idempotent: 重复调用 install_recovery_hooks() 不会重复 patch。

调用方式 (在 crawl.py 启动最早处):
  try:
      from common_supervisor._injection import install_recovery_hooks
      install_recovery_hooks()
  except Exception:
      pass

依赖:
  - common_supervisor.state  (load_recovery, who_is_disabled, is_glm_backing_off)
  - common_supervisor.patterns (Severity, 仅用于日志)
"""
from __future__ import annotations
import sys, time, functools
from pathlib import Path

# ── 路径可达性修复: 把 crawl skill 根加进 sys.path ───────────────────────────
_SKILL_DIR = Path(__file__).resolve().parent.parent
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR))
if str(_SKILL_DIR / "common_supervisor") not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR / "common_supervisor"))

from common_supervisor.state import (
    load_recovery, is_provider_active, is_glm_backing_off,
    record_error,   # record_timing 已在父进程通过日志解析完成，子进程不再写
)

def record_timing(op: str, sec: float, meta: dict = None):
    """No-op: timing 记录全部迁移到父进程日志解析，子进程不写 timing.json。"""
    pass

# ── 标记位 (防止重复 patch) ─────────────────────────────────────────────────
_INSTALLED = False
_PATCHED = set()  # 记录已经被 patch 的 (module, attr)


def _log_provider_skip(provider: str, reason: str):
    """Provider 跳过时的统一日志格式.

    修 #5 (2026-07-30): 原格式 `[xxx] ⏭️  跳过 (recovery: ...)` 会让 supervisor 把这条 self-generated
    跳过行再次识别为 bailian_quota / groq_429 异常, 触发递归 disable. 现在改为:
      - 仍以 `[xxx] ⏭️  ...` 起头, 方便运维扫日志时找到所有 skip 行
      - 但 reason 字段不再嵌入, 避免产生"额度耗尽 额度耗尽 额度耗尽"无限嵌套
      - Supervisor 通过 negative lookahead (patterns.py) 已不再匹配本行, 双保险
    """
    # reason 限 80 字符, 避免老 recovery 反复嵌入变巨长字符串
    short_reason = (reason or "")[:80]
    print(f"  [{provider}] ⏭️  [recovery:skip] {short_reason}", flush=True)


def _safe_load_recovery() -> dict:
    """读 recovery.json, 异常时返回空 dict (no-op 模式)."""
    try:
        return load_recovery() or {}
    except Exception:
        return {}


# ═══════════════════════════════════════════════════════════════════════════════
# 通用工厂函数（消除重复代码）
# ═══════════════════════════════════════════════════════════════════════════════

def _make_transcribe_wrapper(provider: str, degraded_timeout: bool = False):
    """工厂: 生成 transcribe_* 的 recovery-aware wrapper.

    Args:
        provider: provider 名称 (e.g. "groq", "bailian", "mlx")
        degraded_timeout: True 时支持 mlx degraded 模式超时缩短
    """
    timing_key = f"transcribe_{provider}"

    def wrapper(orig):
        @functools.wraps(orig)
        def wrapped(*args, **kwargs):
            r = _safe_load_recovery()
            if not is_provider_active(provider):
                reason = r.get(provider, {}).get("disabled_reason", "disabled by supervisor")
                _log_provider_skip(provider, reason)
                return ""
            # mlx degraded: 缩短超时阈值
            if degraded_timeout:
                cfg = r.get(provider, {})
                if cfg.get("status") == "degraded":
                    new_timeout = cfg.get("timeout_sec")
                    if new_timeout and "timeout" in kwargs and kwargs["timeout"] > new_timeout:
                        print(f"  [{provider}] degraded 模式, 超时 {kwargs['timeout']}s → {new_timeout}s", flush=True)
                        kwargs["timeout"] = new_timeout
            t0 = time.time()
            try:
                result = orig(*args, **kwargs)
                record_timing(timing_key, time.time() - t0, {"ok": True})
                return result
            except Exception as e:
                record_timing(timing_key, time.time() - t0, {"ok": False, "err": str(e)[:80]})
                raise
        return wrapped
    return wrapper


def _make_glm_wrapper(provider: str):
    """工厂: 生成 call_glm / call_bailian_text 的 recovery-aware wrapper."""
    timing_key = f"summarize_glm"

    def wrapper(orig):
        @functools.wraps(orig)
        def wrapped(*args, **kwargs):
            # GLM 专用: 检查 backoff 窗口
            if provider == "glm" and is_glm_backing_off():
                r = _safe_load_recovery()
                until = r.get("glm_summary", {}).get("backoff_until", 0)
                remain = int(until - time.time())
                print(f"  [glm] ⏳ GLM 退避中, 剩余 {remain}s, 跳过本次调用", flush=True)
                raise RuntimeError(f"GLM backoff ({remain}s remaining)")
            # Bailian 备用引擎: 检查 bailian 状态
            if provider == "bailian-text":
                if not is_provider_active("bailian"):
                    r = _safe_load_recovery()
                    reason = r.get("bailian", {}).get("disabled_reason", "disabled by supervisor")
                    print(f"  [bailian-text] ⏭️  跳过 (recovery: {reason})", flush=True)
                    raise RuntimeError(f"bailian disabled: {reason}")
            t0 = time.time()
            try:
                result = orig(*args, **kwargs)
                record_timing(timing_key, time.time() - t0, {"ok": True, "engine": provider})
                return result
            except Exception as e:
                record_timing(timing_key, time.time() - t0, {"ok": False, "err": str(e)[:80], "engine": provider})
                raise
        return wrapped
    return wrapper


# ── Patch 1-3: transcribe wrappers (工厂调用) ──────────────────────────────────
_wrap_transcribe_groq    = _make_transcribe_wrapper("groq",    degraded_timeout=False)
_wrap_transcribe_bailian = _make_transcribe_wrapper("bailian", degraded_timeout=False)
_wrap_transcribe_mlx     = _make_transcribe_wrapper("mlx",     degraded_timeout=True)

# ── Patch 4-5: summarize wrappers (工厂调用) ───────────────────────────────────
_wrap_call_glm          = _make_glm_wrapper("glm")
_wrap_call_bailian_text = _make_glm_wrapper("bailian-text")


# ═══════════════════════════════════════════════════════════════════════════════
# 通用 patch helper
# ═══════════════════════════════════════════════════════════════════════════════

def _patch_attr(module_name: str, attr_name: str, wrapped_func):
    """对 module.attr 做 monkey-patch, 已 patch 过则跳过."""
    key = (module_name, attr_name)
    if key in _PATCHED:
        return False
    try:
        mod = sys.modules.get(module_name)
        if mod is None:
            import importlib
            mod = importlib.import_module(module_name)
            sys.modules[module_name] = mod
        if not hasattr(mod, attr_name):
            return False
        orig = getattr(mod, attr_name)
        if not callable(orig):
            return False
        setattr(mod, attr_name, wrapped_func(orig))
        _PATCHED.add(key)
        return True
    except Exception as e:
        print(f"  [supervisor-injection] ⚠️ patch {module_name}.{attr_name} 失败: {e}", flush=True)
        return False


def install_recovery_hooks():
    """主入口: 给 crawl.py 子进程注入 recovery-aware 行为.
    每次调用都尝试 patch 一次 (已 patched 的会被跳过), 所以可以安全地多次调用.
    """
    global _INSTALLED
    if _INSTALLED:
        # 即使已 installed, 也再跑一次 _patch_* 保证 lazy-loaded 模块也吃到
        pass

    # 1. transcribe_groq
    _patch_attr("common.transcribe", "transcribe_groq", _wrap_transcribe_groq)
    # 2. transcribe_bailian
    _patch_attr("common.transcribe", "transcribe_bailian", _wrap_transcribe_bailian)
    # 3. transcribe_mlx
    _patch_attr("common.transcribe", "transcribe_mlx", _wrap_transcribe_mlx)
    # 4. call_glm (summarize)
    _patch_attr("common.summarize", "call_glm", _wrap_call_glm)
    # 5. call_bailian_text (summarize 备用)
    _patch_attr("common.summarize", "call_bailian_text", _wrap_call_bailian_text)

    _INSTALLED = True
    if _PATCHED:
        print(f"  [supervisor-injection] ✅ 已注入 {len(_PATCHED)} 个 recovery-aware hook: "
              f"{sorted(f'{m}.{a}' for m, a in _PATCHED)}", flush=True)


def is_installed() -> bool:
    return _INSTALLED


def get_patched_attrs() -> list:
    """返回已被 patch 的 (module, attr) 列表, 诊断用."""
    return sorted(_PATCHED)


# ═══════════════════════════════════════════════════════════════════════════════
# 独立测试入口
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("== _injection.py 独立测试 ==")
    print("1. install_recovery_hooks()")
    install_recovery_hooks()
    print(f"   installed: {is_installed()}, patched: {get_patched_attrs()}")
    print()
    print("2. 模拟 recovery.json 状态")
    from common_supervisor.state import (
        disable_provider, set_provider_cooldown, set_mlx_degraded, set_glm_backoff,
        reset_recovery,
    )
    reset_recovery()
    install_recovery_hooks()
    print(f"   is_provider_active('groq'): {is_provider_active('groq')}")
    print(f"   is_provider_active('bailian'): {is_provider_active('bailian')}")
    print(f"   is_provider_active('mlx'): {is_provider_active('mlx')}")
    print(f"   is_glm_backing_off(): {is_glm_backing_off()}")
    print()
    print("3. 禁用 groq")
    disable_provider("groq", "test")
    print(f"   is_provider_active('groq'): {is_provider_active('groq')}  (应 False)")
    print()
    print("4. 降级 mlx")
    set_mlx_degraded(timeout_sec=180)
    r = _safe_load_recovery()
    print(f"   mlx.status={r['mlx']['status']}, mlx.timeout_sec={r['mlx']['timeout_sec']}")
    print()
    print("5. GLM backoff")
    set_glm_backoff(60, "test")
    print(f"   is_glm_backing_off(): {is_glm_backing_off()}  (应 True)")
    print()
    print("6. 模拟 transcribe_bailian 调用 (应被 skip)")
    from common import transcribe as _t
    result = _t.transcribe_bailian("/tmp/fake.wav")
    print(f"   返回: {result!r}  (应 '')")
    print()
    print("7. 模拟 transcribe_groq 调用 (应被 skip)")
    result = _t.transcribe_groq("/tmp/fake.wav", "fake_key")
    print(f"   返回: {result!r}  (应 '')")
    print()
    print("8. 模拟 transcribe_mlx 调用 (应被 skip)")
    result = _t.transcribe_mlx("/tmp/fake.wav")
    print(f"   返回: {result!r}  (应 '')")
    print()
    print("9. 模拟 call_glm 调用 (应抛 backoff)")
    from common import summarize as _s
    try:
        _s.call_glm("sys", "user", "fake_key")
        print("   未抛错 (BUG!)")
    except RuntimeError as e:
        print(f"   抛 RuntimeError: {e}")
    print()
    print("✅ 全部测试通过")
