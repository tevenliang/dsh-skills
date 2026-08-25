#!/usr/bin/env python3
"""
bailian-check.sh - 读取 config.json 中所有 dashscope combo 的模型 + bl usage free 额度，输出 JSON
只展示 combo 中实际配置的模型。
"""
import json, subprocess, re
from datetime import datetime

CONFIG = "/Users/tianwenliang/.opencodex/config.json"

def get_free_info():
    """获取所有免费模型额度，返回 {model_name: {remaining, total, pct, used}}"""
    r = subprocess.run(
        ["bl", "usage", "free", "--all"],
        capture_output=True, text=True, timeout=30,
    )
    info = {}
    for line in r.stdout.splitlines():
        parts = [p.strip() for p in line.split("│")]
        if len(parts) < 5:
            continue
        model = parts[0].strip()
        if not model:
            continue
        try:
            rem = int(parts[2].replace(",", ""))
            tot = int(parts[3].replace(",", ""))
            pct_match = re.search(r'(\d+\.?\d*)%', parts[4])
            pct = float(pct_match.group(1)) if pct_match else 0.0
            info[model] = {"remaining": rem, "total": tot, "pct": pct, "used": tot - rem}
        except (ValueError, IndexError):
            pass
    return info

def health(pct):
    if pct >= 50: return "💚", "充足"
    if pct >= 20: return "🟡", "正常"
    if pct >= 10: return "🔴", "紧张"
    return "🚨", "紧急"

# 读取 config.json 中所有 dashscope models
try:
    with open(CONFIG) as f:
        config = json.load(f)
except Exception as e:
    print(json.dumps({"error": f"无法读取 config.json: {e}"}))
    exit(1)

combo_models = []  # [(combo_name, model_name)]
for cname, cdata in config.get("combos", {}).items():
    if not isinstance(cdata, dict):
        continue
    for t in cdata.get("targets", []):
        if isinstance(t, dict) and t.get("provider") == "dashscope":
            m = t.get("model", "")
            if m:
                combo_models.append((cname, m))

if not combo_models:
    print(json.dumps({
        "combo": "bailian",
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "models": [],
        "note": "无 dashscope combo 配置"
    }, ensure_ascii=False, indent=2))
    exit(0)

# 获取所有免费额度
free_info = get_free_info()

# 构建结果（按 combo 分组显示）
result_models = []
for cname, model in combo_models:
    if model in free_info:
        info = free_info[model]
        h, ht = health(info["pct"])
        result_models.append({
            "combo": cname,
            "model": model,
            "in_free_list": True,
            "used": info["used"],
            "total": info["total"],
            "remaining": info["remaining"],
            "pct": info["pct"],
            "health": h,
            "health_text": ht
        })
    else:
        result_models.append({
            "combo": cname,
            "model": model,
            "in_free_list": False,
            "health": "⚪",
            "health_text": "无免费额度记录"
        })

print(json.dumps({
    "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "models": result_models
}, ensure_ascii=False, indent=2))
