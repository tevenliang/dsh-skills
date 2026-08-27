#!/usr/bin/env python3
"""Test Groq API"""
import json
import subprocess

# Read API key
key_file = '/home/ubuntu/.agents/credentials/ominicrawl/groq.json'
with open(key_file) as f:
    api_key = json.load(f)['api_key']

print(f"API Key: {api_key[:20]}...")

# Test simple completion
payload = {
    "model": "llama-3.1-70b-versatile",
    "messages": [{"role": "user", "content": "Say 'hello' in one word"}],
    "max_tokens": 10
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
