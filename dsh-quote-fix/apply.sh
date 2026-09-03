#!/usr/bin/env bash
# dsh-quote-fix: 一键重放 MiniMax 额度适配补丁（幂等，重复执行安全）
# 用法: ./apply.sh [dsh-service安装目录]   （或用环境变量 DSSVC_DIR=...）
# 默认探测路径: $HOME/.dsh/profiles/web/node_modules/@gehennawu/dsh-service
set -u

CANDIDATES=(
  "${DSSVC_DIR:-}"
  "/home/ubuntu/.dsh/profiles/web/node_modules/@gehennawu/dsh-service"
  "$HOME/.dsh/profiles/web/node_modules/@gehennawu/dsh-service"
)
DSSVC_DIR="${1:-}"
if [ -n "$DSSVC_DIR" ]; then CANDIDATES=("$DSSVC_DIR"); fi

DSSVC_DIR=""
for d in "${CANDIDATES[@]}"; do
  if [ -n "$d" ] && [ -f "$d/quota-adapters.js" ] && [ -f "$d/client.js" ]; then
    DSSVC_DIR="$d"; break
  fi
done
if [ -z "$DSSVC_DIR" ]; then
  echo "✗ 未找到 dsh-service 安装目录（需要 quota-adapters.js + client.js），请用: ./apply.sh <path>" >&2
  exit 1
fi
echo "→ dsh-service 目录: $DSSVC_DIR"

export DSSVC_DIR
python3 << 'PYEOF'
import os, re, sys, subprocess

base = os.environ["DSSVC_DIR"]
adapters_path = os.path.join(base, "quota-adapters.js")
client_path   = os.path.join(base, "client.js")

def read_t(p): return open(p, encoding="utf-8").read()
def write_t(p, c):
    open(p, "w", encoding="utf-8").write(c)
    print(f"  ✓ 已写回 {os.path.basename(p)}")

ok = True

# ---------- Patch1a: fetchMiniMaxUsage 函数 ----------
MINIMAX_FN = '''// MiniMax Coding Plan（v1.0 自定义适配器）
// 端点: https://www.minimaxi.com/v1/api/openplatform/coding_plan/remains
// 认证: Bearer token（API Key）
// 响应: { base_resp: { status_code, status_msg }, model_remains: [...] }（无 data 层！）
const MINIMAX_CODING_PLAN_URL = 'https://www.minimaxi.com/v1/api/openplatform/coding_plan/remains'

async function fetchMiniMaxUsage({ credential, signal, requestJson }) {
  if (typeof requestJson !== 'function') throw new Error('transport-unavailable')
  const token = typeof credential === 'string' ? credential.trim() : ''
  if (token === '') throw new Error('credential-missing')
  let payload
  // credential 已由 policy.format 加上 'Bearer ' 前缀，直接当 Authorization 头用（勿重复加前缀）
  try {
    payload = await requestJson(MINIMAX_CODING_PLAN_URL, {
      headers: { Authorization: token },
      signal,
    })
  } catch (error) {
    if (error?.message === 'http-status:401' || error?.message === 'http-status:403') throw new Error('credential-rejected')
    throw error
  }
  const resp = payload
  const code = typeof resp?.base_resp?.status_code === 'number' ? resp.base_resp.status_code : -1
  if (code !== 0) {
    const msg = typeof resp?.base_resp?.status_msg === 'string' ? resp.base_resp.status_msg : 'unknown'
    // MiniMax 用 status_code 1004 表示凭据缺失/无效（"cookie is missing"）
    const err = new Error(code === 1004 || code === 401 || code === 403 ? 'credential-rejected' : 'bad-payload')
    err.detail = msg
    throw err
  }
  // model_remains 直接在顶层
  const items = Array.isArray(resp?.model_remains) ? resp.model_remains : []
  if (items.length === 0) throw new Error('no-subscription')
  const windows = []
  const seen = new Set()
  for (const item of items) {
    if (item === null || typeof item !== 'object') continue
    const name = typeof item.model_name === 'string' ? item.model_name : ''
    if (name === '' || seen.has(name)) continue
    // 跳过 video；只保留 general
    if (name !== 'general') continue
    seen.add(name)
    // remaining_percent 是「剩余」，UI 进度条要「已用」= 100 - remaining
    const pct5hRemain = Number(item.current_interval_remaining_percent)
    const pctWeekRemain = Number(item.current_weekly_remaining_percent)
    if (Number.isFinite(pct5hRemain)) {
      windows.push({
        id: '5h',
        kindKey: 'tokens-limit-u3-n5',
        percent: Math.max(0, Math.min(100, Math.round(100 - pct5hRemain))),
      })
    }
    if (Number.isFinite(pctWeekRemain)) {
      windows.push({
        id: 'weekly',
        kindKey: 'tokens-limit-u6-n1',
        percent: Math.max(0, Math.min(100, Math.round(100 - pctWeekRemain))),
      })
    }
  }
  if (windows.length === 0) throw new Error('no-subscription')
  return windows
}

'''

c = read_t(adapters_path)
if 'async function fetchMiniMaxUsage' in c:
    print("  = Patch1a (fetchMiniMaxUsage 函数) 已存在，跳过")
else:
    anchor = "const CLIPROXY_CODEX_USAGE_URL = 'https://chatgpt.com/backend-api/wham/usage'"
    if anchor in c:
        c = c.replace(anchor, MINIMAX_FN + anchor, 1)
        print("  ✓ Patch1a (fetchMiniMaxUsage 函数) 已插入")
    else:
        print("  ✗ Patch1a 锚点未找到（CLIPROXY_CODEX_USAGE_URL），需手工处理", file=sys.stderr)
        ok = False

# ---------- Patch1b: minimax catalog 条目 ----------
CATALOG_ENTRY = '''    createComposedAdapter({
      kind: 'minimax',
      fetch: fetchMiniMaxUsage,
      keyHints: ['MINIMAX_API_KEY'],
      includeProfileHint: false,
      format: 'bearer',
      hosts: ['minimaxi.com', 'minimax.io'],
      usageUrl: 'https://www.minimaxi.com/coding-plan',
    }),
'''
if "kind: 'minimax'" in c:
    print("  = Patch1b (minimax catalog 条目) 已存在，跳过")
else:
    m = re.search(r"usageUrl: 'https://platform\.stepfun\.com/plan-usage',\r?\n    \}\),\r?\n  \]\)", c)
    if m:
        c = c[:m.end() - len("  ])")] + CATALOG_ENTRY + c[m.end() - len("  ])"):]
        print("  ✓ Patch1b (minimax catalog 条目) 已插入")
    else:
        print("  ✗ Patch1b 锚点未找到（stepfun-step-plan catalog 结尾），需手工处理", file=sys.stderr)
        ok = False
write_t(adapters_path, c)

# ---------- Patch3: client.js bt 数组 ----------
c = read_t(client_path)
m = re.search(r'bt=\[([^\]]*)\]', c)
if m and '"minimax"' in m.group(1):
    print("  = Patch3 (bt 数组已有 minimax) 跳过")
elif m:
    inner = m.group(1).rstrip()
    c = c[:m.start()] + 'bt=[' + inner + ',"minimax"]' + c[m.end():]
    print("  ✓ Patch3 (bt 数组加 minimax) 已完成")
else:
    print("  ✗ Patch3 锚点未找到（bt=[...]），需手工处理", file=sys.stderr)
    ok = False

# ---------- Patch4+5: client.js 中英翻译（各自独立幂等） ----------
TRANS = ',"quota.kind.minimax":"MiniMax Coding Plan"'

def zh_marker():
    return re.search(r'"quota\.kind\.xiaomi-token-plan-cn":"小米[^"]*"', c)

def en_marker():
    first = re.search(r'"quota\.kind\.xiaomi-token-plan-cn":"[^"]*"', c)
    if first is None: return None
    return re.compile(r'"quota\.kind\.xiaomi-token-plan-cn":"[^"]*"').search(c, pos=first.end() + 1)

for label, finder in (("Patch4 (中文翻译)", zh_marker), ("Patch5 (英文翻译)", en_marker)):
    m = finder()
    if m is None:
        print(f"  ✗ {label} 锚点未找到", file=sys.stderr)
        ok = False
        continue
    tail = c[m.end():m.end() + 60]
    if 'quota.kind.minimax' in tail:
        print(f"  = {label} 已存在，跳过")
    else:
        c = c[:m.end()] + TRANS + c[m.end():]
        print(f"  ✓ {label} 已插入")
write_t(client_path, c)

# ---------- 语法校验 ----------
for p in (adapters_path, client_path):
    r = subprocess.run(["node", "--check", p], capture_output=True, text=True)
    if r.returncode == 0:
        print(f"  ✓ 语法校验通过: {os.path.basename(p)}")
    else:
        print(f"  ✗ 语法校验失败: {os.path.basename(p)}\n{r.stderr[:2000]}", file=sys.stderr)
        ok = False

print()
if ok:
    print("🎯 全部补丁应用完成。下一步：征得用户同意后重启 dsh-web，浏览器硬刷新，验证额度查询。")
else:
    print("⚠ 部分补丁未应用，请按输出信息手工处理（参考 patches/ 目录素材）。", file=sys.stderr)
    sys.exit(1)
PYEOF