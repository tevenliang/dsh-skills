#!/usr/bin/env python3
import json
import subprocess

# Test Bailian API
config = json.load(open('/home/ubuntu/.bailian/config.json'))
api_key = config['api_key']
endpoint = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

payload = {
    "model": "glm-4-flash",
    "messages": [{"role": "user", "content": "用一句话总结: 今天天气很好"}],
    "max_tokens": 50
}

cmd = [
    "curl", "-s", "--proxy", "http://127.0.0.1:7890",
    "-X", "POST", endpoint,
    "-H", f"Authorization: Bearer {api_key}",
    "-H", "Content-Type: application/json",
    "-d", json.dumps(payload)
]

result = subprocess.run(cmd, capture_output=True, text=True)
print("Status:", result.returncode)
print("Response:", result.stdout[:500] if result.stdout else result.stderr[:200])
