#!/usr/bin/env python3
"""测试 Groq 转录是否添加标点"""
import subprocess
import json
from pathlib import Path

audio_path = Path("/tmp/test.wav")

# Create a small test file (just copy an existing one if available)
# Otherwise just test the API directly

key_file = Path.home() / ".agents/credentials/ominicrawl/groq.json"
api_key = json.loads(key_file.read_text())["api_key"]

prompt = "Chinese, formal, with proper punctuation. 请用中文标点符号。"

cmd = [
    "curl", "-s", "--proxy", "http://127.0.0.1:7890",
    "-X", "POST",
    "https://api.groq.com/openai/v1/audio/transcriptions",
    "-H", f"Authorization: Bearer {api_key}",
    "-F", "model=whisper-large-v3",
    "-F", "language=zh",
    "-F", f"file=@{audio_path}",
    "-F", f"prompt={prompt}",
    "-F", "response_format=text",
]

result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
print("Result:", result.stdout[:500] if result.stdout else "empty")
print("Error:", result.stderr[:200] if result.stderr else "none")
