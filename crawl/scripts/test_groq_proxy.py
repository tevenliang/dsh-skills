#!/usr/bin/env python3
import json
import subprocess

# 读取 Groq API Key
with open("/home/ubuntu/.agents/credentials/ominicrawl/groq.json") as f:
    groq_key = json.load(f)["api_key"]

print(f"Groq Key: {groq_key[:20]}...")

# 测试音频文件
wav_path = "/tmp/test.wav"

# 创建一个小测试音频
cmd = [
    "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
    "-ar", "16000", "-ac", "1", wav_path
]
subprocess.run(cmd, capture_output=True)

# 测试 Groq API
curl_cmd = [
    "curl", "-s", "--proxy", "http://127.0.0.1:7890",
    "-X", "POST",
    "https://api.groq.com/openai/v1/audio/transcriptions",
    "-H", f"Authorization: Bearer {groq_key}",
    "-F", "model=whisper-large-v3",
    "-F", f"file=@{wav_path}",
    "-F", "response_format=text",
]

result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=30)
print(f"Status: {result.returncode}")
print(f"Response: {result.stdout[:200] if result.stdout else result.stderr[:200]}")
