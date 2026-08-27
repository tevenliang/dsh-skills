#!/usr/bin/env python3
"""Test Groq summarization with debug"""
import json
import subprocess
from pathlib import Path

# Read API key
key_file = Path.home() / ".agents/credentials/ominicrawl/groq.json"
api_key = json.loads(key_file.read_text())["api_key"]

print(f"API Key: {api_key[:20]}...")

# Test with Chinese text
test_text = "今天A股三大指数集体上涨，沪指涨1.5%，深成指涨2.0%，创业板指涨2.5%。科技股表现强劲，半导体板块领涨。成交额突破万亿关口，市场情绪明显回暖。"

prompt = f"""请用简洁的语言总结以下内容的核心要点，字数控制在500字以内：

{test_text}

总结："""

payload = {
    "model": "qwen/qwen3.8-27b",
    "messages": [{"role": "user", "content": prompt}],
    "max_tokens": 1024,
    "temperature": 0.3,
}

cmd = [
    "curl", "-s", "--proxy", "http://127.0.0.1:7890",
    "-X", "POST",
    "https://api.groq.com/openai/v1/chat/completions",
    "-H", f"Authorization: Bearer {api_key}",
    "-H", "Content-Type: application/json",
    "-d", json.dumps(payload)
]

print(f"Running curl command...")
result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
print(f"Response: {result.stdout[:1000]}")
