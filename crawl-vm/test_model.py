#!/usr/bin/env python3
"""Test Qwen model for summarization"""
import json
import subprocess

key_file = '/home/ubuntu/.agents/credentials/ominicrawl/groq.json'
with open(key_file) as f:
    api_key = json.load(f)['api_key']

payload = {
    "model": "qwen/qwen3.8-27b",
    "messages": [{"role": "user", "content": "用一句话总结: 今天A股大涨，沪指涨2%。"}],
    "max_tokens": 50
}

cmd = [
    "curl", "-s", "--proxy", "http://127.0.0.1:7890",
    "-X", "POST",
    "https://api.groq.com/openai/v1/chat/completions",
    "-H", f"Authorization: Bearer {api_key}",
    "-H", "Content-Type: application/json",
    "-d", json.dumps(payload)
]

result = subprocess.run(cmd, capture_output=True, text=True)
print(f"Response: {result.stdout[:500]}")
