#!/usr/bin/env python3
"""List available Groq models - full list"""
import json
import subprocess

key_file = '/home/ubuntu/.agents/credentials/ominicrawl/groq.json'
with open(key_file) as f:
    api_key = json.load(f)['api_key']

cmd = [
    "curl", "-s", "--proxy", "http://127.0.0.1:7890",
    "https://api.groq.com/openai/v1/models",
    "-H", f"Authorization: Bearer {api_key}"
]

result = subprocess.run(cmd, capture_output=True, text=True)
data = json.loads(result.stdout)
for m in data.get("data", []):
    print(m["id"])
