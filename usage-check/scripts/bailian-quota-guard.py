#!/usr/bin/env python3
"""
bailian-quota-guard.sh - Bailian 百炼额度守卫
遍历所有 dashscope combo，检查免费额度，低于阈值自动移除模型并重启 opencodex。
日志输出到 scripts/bailian-quota-guard.log
"""
import json, subprocess, shutil, sys
from datetime import datetime

CONFIG = "/Users/tianwenliang/.opencodex/config.json"
LOG_FILE = "/Users/tianwenliang/.agents/skills/System/usage-check/scripts/bailian-quota-guard.log"
THRESHOLD_PCT = 10  # 剩余额度 < 10% 触发禁用

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

# ── helpers ──────────────────────────────────────────────

def get_free_remaining(model):
    """从 bl usage free --all 解析某模型的剩余额度；不可用返回 0."""
    r = subprocess.run(
        ["bl", "usage", "free", "--all"],
        capture_output=True, text=True, timeout=30,
    )
    for line in r.stdout.splitlines():
        parts = [p.strip() for p in line.split("│")]
        if len(parts) >= 5 and parts[0].strip() == model:
            try:
                rem = int(parts[2].replace(",", ""))
                tot = int(parts[3].replace(",", ""))
                pct = float(parts[4].split()[0].rstrip("%"))
                return {"remaining": rem, "total": tot, "pct": pct}
            except (ValueError, IndexError):
                pass
    # 如果 --all 里找不到，尝试单独查
    r2 = subprocess.run(
        ["bl", "usage", "free", "--model", model],
        capture_output=True, text=True, timeout=10,
    )
    out = r2.stdout.strip()
    if not out or "Unsupported" in out or "     -     " in out:
        return None  # 彻底不可用
    try:
        pct_match = __import__("re").search(r'(\d+\.?\d*)%', out)
        pct = float(pct_match.group(1)) if pct_match else 0
        return {"remaining": 0, "total": 1000000, "pct": pct}
    except Exception:
        return None


# ── main ─────────────────────────────────────────────────

log("=" * 48)
log("Bailian Quota Guard 启动")
log(f"阈值: 剩余额度 < {THRESHOLD_PCT}% 将自动禁用")

# 加载配置
try:
    with open(CONFIG) as f:
        config = json.load(f)
except FileNotFoundError:
    log("❌ config.json 不存在"); sys.exit(1)
except json.JSONDecodeError:
    log("❌ config.json JSON 解析失败"); sys.exit(1)

combos = config.get("combos", {})
if not combos:
    log("⚠️  无 combos，退出"); sys.exit(0)

# 收集所有 dashscope target
dashscope_models = {}   # model -> [(combo_name, target_dict)]
for cname, cdata in combos.items():
    if not isinstance(cdata, dict):
        continue
    for t in cdata.get("targets", []):
        if not isinstance(t, dict) or t.get("provider") != "dashscope":
            continue
        m = t.get("model", "")
        if m:
            dashscope_models.setdefault(m, []).append((cname, t))

if not dashscope_models:
    log("✅ 无 dashscope targets，退出"); sys.exit(0)

log(f"\n📋 发现 {len(dashscope_models)} 个 dashscope 模型:\n" +
    "\n".join(f"   - {k}" for k in sorted(dashscope_models)))

# 逐个检查额度
to_disable = []       # (model, [combo_names])
checked = {}          # model -> info dict

for model in sorted(dashscope_models):
    info = get_free_remaining(model)
    if info is None:
        log(f"🚫 {model}: 不可用（Unsupported / 耗尽）")
        combo_list = [c for c, _ in dashscope_models[model]]
        to_disable.append((model, combo_list))
    elif info["pct"] < THRESHOLD_PCT:
        emoji = "🚨" if info["pct"] < 5 else "🔴"
        log(f"{emoji} {model}: 剩余 {info['pct']:.1f}% ({info['remaining']:,}/{info['total']:,}) → 待禁用")
        combo_list = [c for c, _ in dashscope_models[model]]
        to_disable.append((model, combo_list))
    else:
        log(f"✅ {model}: 剩余 {info['pct']:.1f}% — OK")
    checked[model] = info

if not to_disable:
    log("\n✅ 全部正常，无需操作")
    sys.exit(0)

# ── 应用改动 ────────────────────────────────────────────

log(f"\n{'='*48}")
log(f"📝 准备禁用 {len(to_disable)} 个模型 …")

# 备份
bk = CONFIG + f".bak-{datetime.now().strftime('%Y%m%d%H%M%S')}"
shutil.copy2(CONFIG, bk)
log(f"已备份: {bk}")

changes_made = False
for model, combo_list in to_disable:
    for cname in combo_list:
        if cname not in config.get("combos", {}):
            continue
        targets = config["combos"][cname]["targets"]
        before = len(targets)
        config["combos"][cname]["targets"] = [
            t for t in targets if t.get("model") != model
        ]
        after = len(config["combos"][cname]["targets"])
        if before > after:
            changes_made = True
            log(f"✂️  {cname}: 移除 {model} ({before}→{after})")
            if after == 0:
                config["combos"][cname]["disabled"] = True
                log(f"⛔ {cname}: 无剩余目标，已标记 disabled")

if changes_made:
    with open(CONFIG, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    log("💾 配置已写入")

    # 重启 opencodex
    rs = subprocess.run(["opencodex", "restart"], capture_output=True, text=True)
    if rs.returncode == 0:
        log("✅ opencodex 已重启")
    else:
        log(f"⚠️  opencodex restart 返回码 {rs.returncode}: {rs.stderr[:200]}")
else:
    log("ℹ️  没有实际变更（目标已被其他守卫移除）")

log("\n" + "=" * 48)
log("Bailian Quota Guard 完成")
