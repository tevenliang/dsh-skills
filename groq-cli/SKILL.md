---
name: groq-cli
metadata:
  version: 1.1.0
description: 'Groq API 语音转写（Whisper）+ 文本模型调用。凭证存于
  `~/.agents/credentials/ominicrawl/groq.json`（格式：`{"api_key": "gsk_..."}`）。
  优先用于 ASR（480 分钟/天免费额度，速度极快），text 模型兜底。'
disable-model-invocation: true
---

# Groq CLI / API

## 凭证

路径：`~/.agents/credentials/ominicrawl/groq.json`

格式：
```json
{"api_key": "gsk_xxx"}
```

## ⚠️ 调用铁律

**音频转录必须用 `curl` 或 `multipart/form-data`，绝对不能用 JSON body！**

```bash
# ✅ 正确：multipart form-data 上传音频文件
curl -X POST https://api.groq.com/openai/v1/audio/transcriptions \
  -H "Authorization: Bearer $KEY" \
  -F "model=whisper-large-v3" \
  -F "language=zh" \
  -F "file=@/tmp/my_audio.wav;type=audio/wav"

# ❌ 错误：JSON body 发音频（永远 403 Forbidden）
curl -X POST https://api.groq.com/openai/v1/audio/transcriptions \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"whisper-large-v3","file":"@/tmp/my_audio.wav"}'  # ← 永远失败
```

**Python 调用也必须用 `multipart`（`requests` 库或 `urllib.request` + `encode()`），不要用纯 JSON。**

## 🎤 ASR（语音转文字）

### 可用模型

| 模型 | 说明 | 备注 |
|------|------|------|
| `whisper-large-v3` | **推荐**，中文识别好 | 默认 |
| `whisper-large-v3-turbo` | 更快，精度略低 | 备选 |

### curl 调用（推荐，零出错）

```bash
KEY=$(python3 -c "import json; print(json.load(open('/Users/tianwenliang/.agents/credentials/ominicrawl/groq.json'))['api_key'])")

curl -s -w "\nHTTP %{http_code}" \
  -X POST https://api.groq.com/openai/v1/audio/transcriptions \
  -H "Authorization: Bearer $KEY" \
  -F "model=whisper-large-v3" \
  -F "language=zh" \
  -F "file=@/tmp/my_audio.wav;type=audio/wav"
```

成功返回：
```json
{"text":"识别出的文字内容...","x_groq":{"id":"req_xxx"}}
HTTP 200
```

失败返回（429 / 401 / 403）：
```
{"error":{"message":"...","code":"..."}}
HTTP 429
```

### Python 调用（multiprocessing / urllib）

```python
import subprocess, json, os

key = json.load(open(os.path.expanduser("~/.agents/credentials/ominicrawl/groq.json")))["api_key"]
wav_path = "/tmp/my_audio.wav"

# 用 curl subprocess（最可靠）
result = subprocess.run(
    ["curl", "-s", "-w", "\\nHTTP %{http_code}",
     "-X", "POST", "https://api.groq.com/openai/v1/audio/transcriptions",
     "-H", f"Authorization: Bearer {key}",
     "-F", f"model=whisper-large-v3",
     "-F", "language=zh",
     "-F", f"file=@{wav_path};type=audio/wav"],
    capture_output=True, text=True, timeout=120
)
lines = result.stdout.strip().split("\n")
http_code = lines[-1]
body = "\n".join(lines[:-1])

if http_code == "200":
    text = json.loads(body)["text"]
    print(f"OK: {text}")
elif http_code == "429":
    print("Rate limited — 冷却后再试或切 Bailian")
else:
    print(f"Error {http_code}: {body}")
```

### Smoke test

```bash
KEY=$(python3 -c "import json; print(json.load(open('/Users/tianwenliang/.agents/credentials/ominicrawl/groq.json'))['api_key'])")

curl -s -w "\nHTTP %{http_code}" \
  -X POST https://api.groq.com/openai/v1/audio/transcriptions \
  -H "Authorization: Bearer $KEY" \
  -F "model=whisper-large-v3" \
  -F "language=zh" \
  -F "file=@/tmp/asr_longer.wav;type=audio/wav"
```

预期：`HTTP 200` + 识别文字。

## 📊 查 Groq 模型列表（验证 key 有效）

```bash
KEY=$(python3 -c "import json; print(json.load(open('/Users/tianwenliang/.agents/credentials/ominicrawl/groq.json'))['api_key'])")

curl -s https://api.groq.com/openai/v1/models \
  -H "Authorization: Bearer $KEY" | \
  python3 -c "import json,sys; d=json.load(sys.stdin); [print(m['id']) for m in d['data'] if 'whisper' in m['id']]"
```

预期输出：`whisper-large-v3` 和 `whisper-large-v3-turbo`。

## 📋 Groq 在 crawl 中的角色

crawl 爬取使用 Groq 的逻辑（来自 `common_supervisor/recovery.py`）：

- **第 1 次真实 429** → 120s cooldown，当前音频切 Bailian
- **真正连续 2 次 429** → 300s（5 分钟）cooldown，切 Bailian
- **中间出现一次 Groq 成功** → 连续失败计数清零，supervisor cooldown 恢复 active
- **第 1 次 401** → 永久禁用 Groq，切 Bailian
- **连续 2 次 timeout** → 禁用 Groq，切 Bailian

Groq 是 ASR 首选（Bailian 兜底），每日免费额度 480 分钟，速度极快（音频时长 1~2x）。

## 错误代码：必须用人话解释

| HTTP / 现象 | 人话含义 | crawl 处理 |
|------------|----------|------------|
| 200 | Groq 已成功转写 | 返回正文；清连续失败计数和 cooldown |
| 401 | API key 无效、过期或被撤销 | 禁用 Groq，切 Bailian；不要重试同一 key |
| 403 | 请求格式/权限错误；ASR 最常见是错误地用 JSON，而不是 multipart 上传文件 | 记程序请求错误，切 fallback；不要说成额度耗尽 |
| 429 | **确实是 Groq 返回的限流**；可能命中 RPM、RPD、每小时音频秒数 ASH、每天音频秒数 ASD 中任意一项 | 首次冷却 120s；真正连续两次冷却 300s |
| 500/502/503 | Groq 服务端或网关临时错误 | 当前音频 fallback；不能计成 429 |
| timeout | 上传或模型处理超过客户端等待时间；没有收到 HTTP 429 | 当前音频 fallback；不能说“额度耗尽” |
| 非 JSON | 网关、代理或网络层返回了 HTML/空响应 | 记录 HTTP code 和响应长度后 fallback |

### 429 诊断铁律

1. **HTTP 429 本身只能由 Groq/其网关返回，crawl 代码不能凭空制造 HTTP 429。**
2. 但旧版 crawl 曾经会**放大 429 的影响**：
   - 成功后没有清 supervisor 连续失败计数，两个不相邻的 429 被误算成“连续两次”；
   - 新批次先 spawn 再 reset，子进程可能读到上一轮残留 cooldown；
   - supervisor 自生成的 recovery skip 日志会再次触发 pattern，形成递归 disable。
3. “本批只成功转写 3 次”不等于 Groq 只收到 3 个请求：rolling-hour（滚动一小时）会包含本批前的 smoke test、重启前请求、失败/超时请求；ASH/ASD 按提交音频时长计，不按成功篇数计。
4. **不能只凭 429 猜是哪项额度。**必须记录响应 body、`retry-after`、`x-ratelimit-*` 和 request id。旧日志只留下状态码，无法事后证明当时命中 RPM、ASH 还是其他限制。
5. 日志解释必须明确写：`429 限流`、`timeout 单请求超时`、`5xx 服务端错误`，禁止统称“Groq 不稳定”。

### 2026-07-30 crawl 修复记录

- `common_supervisor/patterns.py`：过滤 supervisor 自生成 skip/recovery 行，防止递归触发。
- `common_supervisor/recovery.py`：Groq 成功后清连续失败计数和 cooldown；429 单次 120s、连续两次 300s。
- `common_supervisor/supervisor.py`：新批次在 spawn 子进程前 reset recovery。
- `common-asr/transcribe.py`：区分 401/403/429/5xx/timeout，并输出 429 的响应详情。
- commit：`3a3a2fc fix(crawl): 修复 supervisor recovery 自递归与 Groq 误降级`。
