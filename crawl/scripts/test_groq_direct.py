#!/usr/bin/env python3
import json
import subprocess
import tempfile
from pathlib import Path

PROXY = "http://127.0.0.1:7890"

# 读取 Groq API Key
with open("/home/ubuntu/.agents/credentials/ominicrawl/groq.json") as f:
    groq_key = json.load(f)["api_key"]

print(f"Groq Key: {groq_key[:20]}...")

# 创建测试音频 - 2秒正弦波
with tempfile.TemporaryDirectory() as tmpdir:
    wav_path = Path(tmpdir) / "test.wav"
    
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-ar", "16000", "-ac", "1", str(wav_path)
    ]
    r = subprocess.run(cmd, capture_output=True)
    print(f"Created test audio: {wav_path.stat().st_size} bytes")

    # 测试 Groq API
    print("\n调用 Groq API...")
    groq_cmd = [
        "curl", "-s", "--proxy", PROXY,
        "-X", "POST",
        "https://api.groq.com/openai/v1/audio/transcriptions",
        "-H", f"Authorization: Bearer {groq_key}",
        "-F", "model=whisper-large-v3",
        "-F", f"file=@{wav_path}",
        "-F", "response_format=text",
    ]
    
    print(f"Command: {' '.join(groq_cmd[:5])}...")
    
    r = subprocess.run(groq_cmd, capture_output=True, text=True, timeout=30)
    print(f"Return code: {r.returncode}")
    print(f"Stdout length: {len(r.stdout)}")
    print(f"Stdout: {r.stdout[:500] if r.stdout else 'EMPTY'}")
    print(f"Stderr: {r.stderr[:200] if r.stderr else 'EMPTY'}")
