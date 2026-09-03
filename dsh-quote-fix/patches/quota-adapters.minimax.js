// patches/quota-adapters.minimax.js
// 插入位置: quota-adapters.js 中 `const CLIPROXY_CODEX_USAGE_URL = ...` 之前
// 内容与 apply.sh 中 Patch1a 相同（人工核对用副本）

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
    const err = new Error(code === 1004 || code === 401 || code === 403 ? 'credential-rejected' : 'bad-payload')
    err.detail = msg
    throw err
  }
  const items = Array.isArray(resp?.model_remains) ? resp.model_remains : []
  if (items.length === 0) throw new Error('no-subscription')
  const windows = []
  const seen = new Set()
  for (const item of items) {
    if (item === null || typeof item !== 'object') continue
    const name = typeof item.model_name === 'string' ? item.model_name : ''
    if (name === '' || seen.has(name)) continue
    if (name !== 'general') continue
    seen.add(name)
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