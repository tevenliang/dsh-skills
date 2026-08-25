#!/usr/bin/env python3
"""
OpenRouter Hot Model Router
Dynamically fetch, rank, recommend, and call OpenRouter models.
"""
import argparse
import json
import os
import sys
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
CACHE_FILE = BASE_DIR / ".model_cache.json"
CACHE_TTL  = 300  # seconds

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE    = "https://openrouter.ai/api/v1"

# ── low-level fetch ───────────────────────────────────────────────────────────

def fetch_models(force=False) -> list[dict]:
    if not force:
        try:
            mtime = os.path.getmtime(CACHE_FILE)
            if (time.time() - mtime) < CACHE_TTL:
                with open(CACHE_FILE) as f:
                    return json.load(f)["data"]
        except Exception:
            pass

    if not OPENROUTER_API_KEY:
        print("ERROR: OPENROUTER_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    import urllib.request
    req = urllib.request.Request(
        f"{OPENROUTER_BASE}/models",
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)

    with open(CACHE_FILE, "w") as f:
        json.dump(data, f)
    return data["data"]

# ── ranking helpers ───────────────────────────────────────────────────────────

def get_weekly_rank(models: list[dict]) -> dict[str, int]:
    """Return {model_id: rank} from OpenRouter's weekly popularity ranking."""
    if not OPENROUTER_API_KEY:
        return {}
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/models/ranking",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            ranking = json.load(resp)
        rank_map = {}
        for i, m in enumerate(ranking.get("models", []), 1):
            rank_map[m.get("id", "")] = i
        return rank_map
    except Exception:
        return {}

def price_per_1m(p: str) -> float:
    try:
        return float(p) * 1_000_000
    except (ValueError, TypeError):
        return float("inf")

# ── formatters ────────────────────────────────────────────────────────────────

def fmt_price(p: str) -> str:
    try:
        v = float(p)
        if v < 0:
            return "dynamic"
        # Prices are per-token; show as per-1M-tokens for readability.
        # Use enough precision: models can be as cheap as ~$0.05/M (5e-8 per token).
        per_1m = v * 1_000_000
        if per_1m < 0.005:
            return f"${per_1m:.4f}"
        elif per_1m < 1:
            return f"${per_1m:.3f}"
        else:
            return f"${per_1m:.2f}"
    except Exception:
        return p

def fmt_row(idx, m, rank) -> str:
    ctx = m.get("context_length", 0) or 0
    pr  = m.get("pricing", {})
    inp = fmt_price(pr.get("prompt", ""))
    out = fmt_price(pr.get("completion", ""))
    name = m.get("name", m["id"])
    flags = []
    mods  = m.get("architecture", {}).get("input_modalities", [])
    if "image" in mods:
        flags.append("🎨")
    if "audio" in mods:
        flags.append("🎙")
    tools = m.get("supported_parameters", [])
    if "tools" in tools:
        flags.append("🔧")
    extra = " ".join(flags)
    r_str = f"#{rank}" if rank else "  "
    return (f"  {r_str:5s}  {name:<45s} ctx:{ctx:>8,}  "
            f"in:{inp:>12s}  out:{out:>12s}  {extra}")

# ── commands ──────────────────────────────────────────────────────────────────

def cmd_list(args):
    models = fetch_models(force=args.refresh)
    rank_map = get_weekly_rank(models)
    # Sort by weekly rank if available, else by id
    def sort_key(m):
        return rank_map.get(m["id"], 999999)
    models_sorted = sorted(models, key=sort_key)

    total = len(models_sorted)
    shown = models_sorted[:args.limit]
    print(f"\n=== OpenRouter Models (total {total}, showing {len(shown)}) ===\n")
    print("  #      Name                                          Context     Input/1M        Output/1M       Features")
    print("  " + "-"*120)
    for i, m in enumerate(shown, 1):
        print(fmt_row(i, m, rank_map.get(m["id"], "")))
    print()

def _filter(models, args) -> list[dict]:
    rank_map = get_weekly_rank(models)

    def score(m):
        r = rank_map.get(m["id"], 999999)
        ctx = m.get("context_length") or 0
        pr  = m.get("pricing", {}).get("prompt", "0")
        cp  = m.get("pricing", {}).get("completion", "0")
        p   = float(pr) + float(cp) * 0.5

        score = 0
        # Popularity
        if args.mode == "popular":
            score -= r * 2
        elif args.mode == "budget":
            score += p * 1e6
        else:  # balanced
            score -= r * 0.5 + p * 5e5

        # Tools
        if args.require_tools:
            if "tools" not in (m.get("supported_parameters") or []):
                score += 1e9
        # Vision
        if args.require_vision:
            mods = m.get("architecture", {}).get("input_modalities", [])
            if "image" not in mods:
                score += 1e9
        # Context
        if args.min_context and ctx < args.min_context:
            score += 1e9

        return score

    return sorted(models, key=score)[:args.limit]

def cmd_recommend(args):
    models = fetch_models(force=args.refresh)
    candidates = _filter(models, args)
    rank_map = get_weekly_rank(models)

    print(f"\n=== Model Recommendations for: {args.task} ===\n")
    for i, m in enumerate(candidates, 1):
        ctx = m.get("context_length", 0) or 0
        pr  = m.get("pricing", {})
        rank = rank_map.get(m["id"], None)
        r_str = f"#{rank}" if rank else "?"
        print(f"  [{i}] {m.get('name', m['id'])}")
        print(f"      ID:    {m['id']}")
        print(f"      Rank:  {r_str} (weekly popularity)")
        print(f"      Context: {ctx:,}")
        print(f"      Input:  {fmt_price(pr.get('prompt',''))}/1M tokens")
        print(f"      Output: {fmt_price(pr.get('completion',''))}/1M tokens")
        print()
    if not candidates:
        print("  No models match the criteria. Try relaxing constraints.\n")

def _installed_skills() -> list[str]:
    skills_dir = Path.home() / ".agents" / "skills"
    if not skills_dir.exists():
        return []
    return [d.name.lower() for d in skills_dir.iterdir() if d.is_dir() and (d / "SKILL.md").exists()]

def cmd_audit_skillhub(args):
    models = fetch_models(force=args.refresh)
    rank_map = get_weekly_rank(models)
    models_sorted = sorted(models, key=lambda m: rank_map.get(m["id"], 999999))[:args.limit]
    installed = _installed_skills()

    print(f"\n=== SkillHub Coverage Audit (top {args.limit}) ===\n")
    covered = 0
    for m in models_sorted:
        mid   = m["id"]
        name  = m.get("name", mid)
        # normalize: strip provider prefix, strip version suffix
        parts = mid.split("/")
        base  = parts[-1].lower().rstrip("-0123456789.")
        # check slug and display name
        match = any(base in s or name.lower() in s for s in installed)
        status = "✅ covered" if match else "❌ missing"
        if match:
            covered += 1
        print(f"  {status}  {name:<45s}  [{mid}]")
    print(f"\n  {covered}/{len(models_sorted)} models have a local skill.\n")

def cmd_call(args):
    if not OPENROUTER_API_KEY:
        print("ERROR: OPENROUTER_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    if not args.models or not args.prompt:
        print("ERROR: --models and --prompt are required", file=sys.stderr)
        sys.exit(1)

    import urllib.request
    payload = {
        "model": args.models[0],
        "messages": [{"role": "user", "content": args.prompt}],
        "max_tokens": args.max_tokens or 1024,
    }
    body = json.dumps(payload).encode()

    req = urllib.request.Request(
        f"{OPENROUTER_BASE}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    print(f"\n  Calling: {args.models[0]}", file=sys.stderr)
    print(f"  Fallback order: {args.models}\n", file=sys.stderr)

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.load(resp)
        msg = result["choices"][0]["message"]["content"]
        used = result.get("model", "unknown")
        print(f"  ✅ Used model: {used}\n")
        print(msg)
    except urllib.error.HTTPError as e:
        body = e.read()
        print(f"  HTTP {e.code}: {body.decode(errors='replace')}", file=sys.stderr)
        sys.exit(1)

# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    import time
    global time
    time = __import__("time")

    parser = argparse.ArgumentParser(description="OpenRouter Hot Model Router")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List top models")
    p_list.add_argument("--limit", type=int, default=10)
    p_list.add_argument("--refresh", action="store_true", help="Force refresh cache")
    p_list.set_defaults(func=cmd_list)

    p_rec = sub.add_parser("recommend", help="Recommend best model for a task")
    p_rec.add_argument("--task", required=True)
    p_rec.add_argument("--limit", type=int, default=5)
    p_rec.add_argument("--mode", choices=["popular","budget","balanced"], default="balanced")
    p_rec.add_argument("--require-tools", action="store_true")
    p_rec.add_argument("--require-vision", action="store_true")
    p_rec.add_argument("--min-context", type=int, default=0)
    p_rec.add_argument("--refresh", action="store_true")
    p_rec.set_defaults(func=cmd_recommend)

    p_aud = sub.add_parser("audit-skillhub", help="Audit SkillHub coverage")
    p_aud.add_argument("--limit", type=int, default=30)
    p_aud.add_argument("--refresh", action="store_true")
    p_aud.set_defaults(func=cmd_audit_skillhub)

    p_call = sub.add_parser("call", help="Call OpenRouter model")
    p_call.add_argument("--models", nargs="+", required=True)
    p_call.add_argument("--prompt", required=True)
    p_call.add_argument("--max-tokens", type=int, default=1024)
    p_call.set_defaults(func=cmd_call)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
