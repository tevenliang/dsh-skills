#!/usr/bin/env python3
"""爬取前检查 bailian text 模型免费配额，写入 state/bailian_quota.json。
由 crawl.py 或 supervisor 在启动时调用一次。"""
# 2026-07-30: 加 bootstrap, 让 subprocess 独立调用时也能 import common_supervisor.*
import sys as _sys
from pathlib import Path as _Path
_SKILL_ROOT = str(_Path(__file__).resolve().parent.parent)
if _SKILL_ROOT not in _sys.path:
    _sys.path.insert(0, _SKILL_ROOT)

import json, subprocess, shutil, re, time as _time
from pathlib import Path

STATE_DIR = Path(__file__).parent.parent / "state"
STATE_FILE = STATE_DIR / "bailian_quota.json"
MODEL_LIST_VAULT = Path(__file__).parent.parent / "模型列表.md"

BAILIAN_ASR_MODELS = [
    "fun-asr-flash-2026-06-15",
    "fun-asr-flash-8k-realtime",
    "fun-asr-flash-8k-realtime-2026-01-28",
    "fun-asr-realtime",
    "fun-asr-realtime-2025-09-15",
    "fun-asr-realtime-2025-11-07",
    "fun-asr-realtime-2026-02-28",
    "fun-asr-2025-08-25",
    "fun-asr-mtl",
    "fun-asr-mtl-2025-08-25",
    "fun-asr-2025-11-07",
]
BAILIAN_TEXT_MODELS = [
    "qwen3.7-max",
    "qwen3.5-flash",
    "qwen3.5-plus",
    "qwen3.5-flash-2026-02-23",
    "qwen3.6-flash",
    "qwen3.6-plus",
    "qwen-plus-latest",
    "deepseek-v3",
    "deepseek-v4-pro",
]

def _resolve_bl_bin():
    """优先 PATH 找 bl，回退 ~/.npm-global/bin/bl（launchd daemon PATH 缺失时）"""
    found = shutil.which("bl") or shutil.which("bailian")
    if found:
        return found
    for name in ("bl", "bailian"):
        cand = Path.home() / ".npm-global" / "bin" / name
        if cand.exists():
            return str(cand)
    return None


BL_BIN = _resolve_bl_bin()
THRESHOLD = 0.10   # <10% 视为不可用

def _check_console_auth() -> dict:
    """验证 console gateway auth (修 #3, 2026-07-30).

    console access_token 8 小时过期, 过期后 bl usage free / summary / stats 全部 NotAuthorised.
    用 bl usage free 验真: 200 = OK, NotAuthorised = 需重 bl auth login --console.
    返回: {ok: bool, reason: str, raw: str}
    """
    if not BL_BIN:
        return {"ok": False, "reason": "bl CLI not found", "raw": ""}
    from common_supervisor._eagain_retry import run_with_retry
    try:
        out = run_with_retry(
            [BL_BIN, "usage", "free", "--model", "qwen3.6-flash", "--output", "json"],
            capture_output=True, text=True, timeout=12, close_fds=True,
        )
        raw = (out.stdout or "") + (out.stderr or "")
        if "NotAuthorised" in raw or "BailianGateway.Team" in raw:
            return {"ok": False,
                    "reason": "NotAuthorised (access_token expired; run: bl auth login --console)",
                    "raw": raw[:300]}
        if out.returncode != 0:
            return {"ok": False, "reason": f"bl exit={out.returncode}", "raw": raw[:300]}
        return {"ok": True, "reason": "console auth OK", "raw": raw[:200]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "bl usage free timeout", "raw": ""}
    except Exception as e:
        return {"ok": False, "reason": f"exception: {e}", "raw": ""}



def _smoke_test_asr(model: str, wav_path: str = "/tmp/asr_longer.wav") -> dict:
    """真实 ASR submit 探测：用 fun-asr-mtl 系测试 (这些支持本地文件)
    返回: { asr_status, asr_task_status, asr_msg, asr_http_status, elapsed }
    """
    import re as _re
    if not BL_BIN:
        return {"asr_status": "CLI_MISSING", "error": "bl CLI not found"}
    if not Path(wav_path).exists():
        return {"asr_status": "WAV_MISSING", "wav": wav_path}
    try:
        from common_supervisor._eagain_retry import run_with_retry
        t0 = _time.time()
        out = run_with_retry(
            [BL_BIN, "speech", "recognize", "--url", wav_path, "--model", model,
             "--language", "zh", "--async", "--output", "json"],
            capture_output=True, text=True, timeout=30, close_fds=True,
        )
        raw = out.stdout + out.stderr
        # 解析 JSON（stdout or stderr, 取决于 success/error）
        mjson = _re.search(r"\{[\s\S]*\}", raw)
        d = json.loads(mjson.group(0)) if mjson else {}
        # 模型支持本地文件上传(经验值: fun-asr-mtl 系)
        support_local = "mtl" in model
        if "error" in d:
            err = d["error"]
            api_code = err.get("api_code", "")
            msg = err.get("message", "")
            if "AllocationQuota" in api_code or "FreeTierOnly" in api_code:
                return {"asr_status": "FREE_QUOTA_EXHAUSTED", "asr_msg": msg[:80], "asr_http": err.get("http_status"), "support_local": support_local}
            if "InvalidParameter" in api_code or "url error" in msg.lower():
                return {"asr_status": "URL_ERROR", "asr_msg": msg[:80], "asr_http": err.get("http_status"), "support_local": support_local}
            if "NotAuthorised" in msg + api_code:
                return {"asr_status": "NOT_AUTHORISED", "asr_msg": msg[:80], "support_local": support_local}
            return {"asr_status": f"ERROR_{api_code or 'unknown'}", "asr_msg": msg[:80], "asr_http": err.get("http_status"), "support_local": support_local}
        if "task_id" in d:
            tid = d["task_id"]
            # poll 1 次
            _time.sleep(2.0)
            poll = run_with_retry(
                [BL_BIN, "video", "task", "get", "--task-id", tid, "--output", "json"],
                capture_output=True, text=True, timeout=15, close_fds=True,
            )
            p_raw = poll.stdout + poll.stderr
            pjson = _re.search(r"\{[\s\S]*\}", p_raw)
            pd = json.loads(pjson.group(0)) if pjson else {}
            ts = pd.get("task_status", "UNKNOWN")
            return {"asr_status": "SUBMIT_OK", "task_status": ts, "task_id": tid, "support_local": support_local, "elapsed": round(_time.time()-t0, 2)}
        return {"asr_status": "UNEXPECTED", "raw": raw[:200]}
    except Exception as e:
        return {"asr_status": "EXCEPTION", "error": str(e)[:100]}


def _quota_rate_limit() -> dict:
    """拿所有 text 模型的 rate limit 上限 (rpm/tpm) — bl quota list (走 console gateway)"""
    if not BL_BIN:
        return {}
    from common_supervisor._eagain_retry import run_with_retry
    try:
        out = run_with_retry(
            [BL_BIN, "quota", "list", "--output", "json"],
            capture_output=True, text=True, timeout=15, close_fds=True,
        )
        d = json.loads(out.stdout)
        if isinstance(d, list):
            return {m["model"]: {"rpm": m.get("rpm", 0), "tpm": m.get("tpm", 0)} for m in d if "model" in m}
        return {}
    except Exception as e:
        return {"_error": str(e)[:80]}


def _query_one(model: str, mode: str = "usage_free") -> dict:
    """mode=usage_free: usage free 查 quota (默认, 文字模型用)
       mode=smoke_asr: 真实 ASR submit 探测 (ASR 模型用)
    """
    if mode == "smoke_asr":
        r = _smoke_test_asr(model)
        ok = r.get("asr_status") == "SUBMIT_OK" and r.get("task_status") == "SUCCEEDED"
        return {"model": model, "available": ok, "ok": False,
                "asr_status": r.get("asr_status"),
                "task_status": r.get("task_status"),
                "asr_msg": r.get("asr_msg", ""),
                "asr_http": r.get("asr_http"),
                "error": "" if ok else r.get("asr_status", "unknown")}

    # mode=usage_free (旧版, 文字模型用)
    if not BL_BIN:
        return {"model": model, "remaining": 0, "total": 0,
                "pct": 0.0, "available": False, "ok": False,
                "error": "bl CLI not found"}
    from common_supervisor._eagain_retry import run_with_retry
    try:
        out = run_with_retry(
            [BL_BIN, "usage", "free", "--model", model],
            capture_output=True, text=True, timeout=15, close_fds=True,
        )
        text = out.stdout + out.stderr
        if "BailianGateway.Team.NotAuthorised" in text or "NotAuthorised" in text:
            return {"model": model, "remaining": 0, "total": 0, "pct": 0.0,
                    "available": False, "ok": False,
                    "error": "BailianGateway.Team.NotAuthorised"}
        m = re.search(r"│\s*(\d[\d,]*)\s*│\s*(\d[\d,]*)\s*│\s*.*?(\d+(?:\.\d+)?)\s*%", text)
        if m:
            remaining = int(m.group(1).replace(",", ""))
            total = int(m.group(2).replace(",", ""))
            pct = float(m.group(3)) / 100.0
            available = pct >= THRESHOLD
            return {"model": model, "remaining": remaining, "total": total,
                    "pct": pct, "available": available, "ok": True}
        return {"model": model, "remaining": 0, "total": 0, "pct": 0.0,
                "available": False, "ok": False, "error": "bl CLI 返回占位 0/0/100%"}
    except Exception as e:
        return {"model": model, "remaining": 0, "total": 0, "pct": 0.0,
                "available": False, "ok": False, "error": str(e)}


def _update_model_list_md(data: dict):
    """重建模型列表.md 的两个表格（文字模型 + 语音模型）"""
    md_path = MODEL_LIST_VAULT
    if not md_path.exists():
        return

    now = data["checked_at"]

    # ── 文字模型 ──────────────────────────────────────────────────
    text_models = sorted(data["models"].items(), key=lambda x: -x[1].get("pct", 0))
    rl = data.get("text_rate_limits", {})
    t_rows = ["| 模型 | 剩余 | 总额 | 剩余% | RPM 上限 | TPM 上限 | 状态 | 备注 |",
              "|------|------:|------:|------:|---------:|---------:|------|------|"]
    for model, info in text_models:
        rem = f"{info['remaining']:,}" if info.get("total") else "—"
        tot = f"{info['total']:,}" if info.get("total") else "—"
        pct = f"{info['pct']*100:.1f}%" if info.get("total") else "—"
        rate = rl.get(model, {})
        rpm = f"{rate['rpm']:,}" if rate.get("rpm") else "—"
        tpm = f"{rate['tpm']:,}" if rate.get("tpm") else "—"
        flag = "✅" if info.get("available") else "⚠️"
        note_parts = []
        if model == data.get("best_model") and info.get("available"):
            note_parts.append("⭐ 推荐")
        if not info.get("total"):
            note_parts.append("⚠️ Console Gateway NotAuthorised (剩余数字拿不到)")
        if rate.get("_error"):
            note_parts.append(f"⚠️ rate_limit 拿不到")
        note = " ".join(note_parts) or "—"
        t_rows.append(f"| `{model}` | {rem} | {tot} | {pct} | {rpm} | {tpm} | {flag} | {note} |")
    t_block = "\n".join(t_rows)
    t_section = (f"## 文字模型（summarize fallback）\n\n"
                  f"> 由 `check_bailian_quota.py` 爬取前自动更新 | 检查时间：{now} | 阈值：<10% 跳过\n\n"
                  f"{t_block}\n")

    # ── 语音模型（仅 free tier）────────────────────────────────────
    asr_models = data.get("asr_models", {})
    asr_list = sorted(asr_models.items(), key=lambda x: 1 if (x[1].get("asr_status")=="SUBMIT_OK" and x[1].get("task_status")=="SUCCEEDED") else 0, reverse=True)
    a_rows = ["| 模型 | 本地/URL | ASR 状态 | 任务状态 | HTTP | 备注 |",
              "|------|:--------:|:--------:|:--------:|:----:|------|"]
    STATUS_EMOJI = {
        "SUBMIT_OK": "✅", "FREE_QUOTA_EXHAUSTED": "❌", "URL_ERROR": "❌",
        "NOT_AUTHORISED": "⚠️", "TIMEOUT": "⏱️", "EXCEPTION": "❌",
        "CLI_MISSING": "❌", "WAV_MISSING": "❌", "UNEXPECTED": "❓",
    }
    for model, info in asr_list:
        st = info.get("asr_status", "UNKNOWN")
        ts = info.get("task_status", "")
        http = info.get("asr_http", "")
        support_local_init = info.get("support_local", False)
        # 实测判定: 成功 submit 本地文件 = ✅ 本地, 其它 (URL_ERROR / 不支持 / 配额尽) = ❌ URL
        is_local_ok = (st == "SUBMIT_OK" and ts == "SUCCEEDED")
        flag = STATUS_EMOJI.get(st, "❓")
        if is_local_ok:
            local_cell = "✅ 本地"
        else:
            local_cell = "❌ URL"
        note_parts = []
        if st == "FREE_QUOTA_EXHAUSTED":
            note_parts.append("🟥 **真配额耗尽**（403 AllocationQuota.FreeTierOnly）")
        elif st == "URL_ERROR":
            if support_local_init:
                note_parts.append("⚠️ URL 校验失败但支持本地")
            else:
                note_parts.append("🟧 不支持本地文件（需 https:// 公网 URL）")
        elif st == "NOT_AUTHORISED":
            note_parts.append("⚠️ Console Gateway 鉴权失败（access_token 过期）")
        elif st == "SUBMIT_OK" and ts == "SUCCEEDED":
            note_parts.append("🟢 **真可用**")
        if info.get("elapsed"):
            note_parts.append(f"{info['elapsed']}s")
        note = " ".join(note_parts)
        a_rows.append(f"| `{model}` | {local_cell} | {flag} {st} | {ts or '—'} | {http or '—'} | {note} |")
    a_rows.append("")
    a_rows.append("### 付费（按量）")
    a_rows.append("")
    a_rows.append("| 模型 | 说明 |")
    a_rows.append("|------|------|")
    a_rows.append("| `sensevoice-v1` | 当前转录主力，OpenAPI 按量付费 |")
    a_rows.append("| `qwen3-asr-flash` | 新一代 ASR，付费 |")
    a_rows.append("| `paraformer-8k-v1` | 老牌 ASR，已无免费额度 |")
    a_rows.append("")
    a_rows.append("### 本地（无限额度）")
    a_rows.append("")
    a_rows.append("| 模型 | 说明 |")
    a_rows.append("|------|------|")
    a_rows.append("| `whisper-small-mlx` | **默认**，mlx-community/whisper-small-mlx |")
    a_rows.append("| `whisper-base-mlx` | 更快，质量稍低 |")
    a_rows.append("| `whisper-tiny-mlx` | 最快，仅英文 |")
    a_block = "\n".join(a_rows)
    a_section = (f"## 语音模型（ASR）\n\n"
                  f"> 付费/本地模型为固定信息，免费额度由 `check_bailian_quota.py` 更新\n\n"
                  f"### 免费额度\n\n{a_block}\n")

    # ── 重建文件 ──────────────────────────────────────────────────
    new_content = f"# Bailian 模型列表\n\n> 由 `check_bailian_quota.py` 爬取前自动更新（{now}）\n\n---\n\n{t_section}\n---\n\n{a_section}"
    md_path.write_text(new_content)

def check_and_write(require_console_auth: bool = True) -> dict:
    """Args:
        require_console_auth: True (默认) 时 console auth 失败 -> 不写 bailian_quota.json,
                              raise SystemExit(2) 让 supervisor 拒绝跑批.
                              False 仅警告继续 (debug 用).
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    results = {}
    best = None

    # 修 #3 (2026-07-30): console auth 前置门
    auth = _check_console_auth()
    if not auth["ok"]:
        msg = ("❌ Bailian console auth 失败: " + auth["reason"] + "\n"
               "   解决: 在终端跑 `bl auth login --console --console-site domestic` 走 OAuth 登录\n"
               "   认证有效期约 8 小时, 跑批前必查\n")
        print(msg)
        if require_console_auth:
            raise SystemExit(2)

    # 查询 ASR 真实可用性 (smoke test)
    asr_results = {}
    for model in BAILIAN_ASR_MODELS:
        asr_results[model] = _query_one(model, mode="smoke_asr")

    # 拿 rate limit 上限 (rpm/tpm) — bl quota list (走 OpenAPI AK/SK, 通常可用)
    rate_limits = _quota_rate_limit()

    # 查询文字模型配额 (mode=usage_free, Console Gateway 通常不可用, 会 fallback 0/0)
    for model in BAILIAN_TEXT_MODELS:  # 串行避免输出混合
        info = _query_one(model, mode="usage_free")
        # 把 rate limit 上限附上去 (如果有)
        if model in rate_limits:
            info["rate_limit_rpm"] = rate_limits[model]["rpm"]
            info["rate_limit_tpm"] = rate_limits[model]["tpm"]
        results[model] = info
        if info["available"]:
            if best is None or info["pct"] > results[best]["pct"]:
                best = model

    payload = {
        "checked_at": _time.strftime("%y-%m-%dT%H:%M:%S"),
        "threshold": THRESHOLD,
        "models": results,
        "asr_models": asr_results,
        "best_model": best,
        "text_rate_limits": rate_limits,
    }
    STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"[bailian_quota] 已写入 {STATE_FILE}")

    # 更新模型列表.md
    try:
        _update_model_list_md(payload)
    except Exception as _e:
        print(f"[bailian_quota] 模型列表.md 更新失败: {_e}")
    print(f"[bailian_quota] 推荐模型: {best} ({results[best]['pct']*100:.1f}%)" if best else "[bailian_quota] 无可用模型")
    return payload


def get_best_model() -> str | None:
    """读缓存，返回当前最佳可用模型，无则 None。"""
    if not STATE_FILE.exists():
        return None
    try:
        data = json.loads(STATE_FILE.read_text())
        return data.get("best_model")
    except Exception:
        return None


if __name__ == "__main__":
    import sys as _sys_cq
    require_console = "--no-require-console" not in _sys_cq.argv
    p = check_and_write(require_console_auth=require_console)
    print(f"\n{'模型':<25} {'剩余':>10} {'总额':>10} {'剩余%':>8} {'可用'}")
    print("-" * 70)
    for model, info in sorted(p["models"].items(), key=lambda x: -x[1]["pct"]):
        flag = "OK" if info["available"] else "SKIP"
        print(f"{model:<25} {info['remaining']:>10,} {info['total']:>10,} "
              f"{info['pct']*100:>7.1f}%  {flag}")



