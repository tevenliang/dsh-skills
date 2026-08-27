#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
common/transcribe.py — 音频转录模块

只使用 Groq (whisper-large-v3, 需要 VPN)
"""
import json
import subprocess
from pathlib import Path
from typing import Optional


class TranscriptionService:
    def __init__(self, config: dict):
        self.model = config.get("model", "whisper-large-v3")
        self.proxy = config.get("proxy", "http://127.0.0.1:7890")
        self.language = config.get("language", "zh")
    
    def transcribe(self, audio_path: Path) -> str:
        """转录音频文件
        
        Args:
            audio_path: WAV 文件路径
            
        Returns:
            转录文本，失败返回空字符串
        """
        if not audio_path.exists() or audio_path.stat().st_size < 1000:
            return ""
        
        return self._groq_transcribe(audio_path)
    
    def _groq_transcribe(self, audio_path: Path) -> str:
        """Groq 转录（需要 VPN）"""
        # 读取 API Key
        key_file = Path.home() / ".agents/credentials/ominicrawl/groq.json"
        if not key_file.exists():
            print(f"    [transcribe] Groq key not found: {key_file}")
            return ""
        
        try:
            api_key = json.loads(key_file.read_text())["api_key"]
        except (json.JSONDecodeError, KeyError) as e:
            print(f"    [transcribe] Failed to read Groq key: {e}")
            return ""
        
        # Groq API 支持 prompt 参数引导 Whisper 添加标点
        prompt = "Chinese, formal, with proper punctuation. 请用中文标点符号。"
        
        # 调用 Groq API
        cmd = [
            "curl", "-s", "--proxy", self.proxy,
            "-X", "POST",
            "https://api.groq.com/openai/v1/audio/transcriptions",
            "-H", f"Authorization: Bearer {api_key}",
            "-F", f"model={self.model}",
            "-F", f"language={self.language}",
            "-F", f"file=@{audio_path}",
            "-F", f"prompt={prompt}",
            "-F", "response_format=text",
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if result.returncode == 0 and result.stdout.strip():
                text = result.stdout.strip()
                print(f"    [transcribe] Groq success: {len(text)} chars")
                return text
            else:
                print(f"    [transcribe] Groq failed: {result.stderr[:100] if result.stderr else result.returncode}")
                return ""
        except subprocess.TimeoutExpired:
            print(f"    [transcribe] Groq timeout")
            return ""
        except Exception as e:
            print(f"    [transcribe] Groq error: {e}")
            return ""


def convert_to_wav(input_path: Path, output_path: Path = None) -> Optional[Path]:
    """将音频文件转换为 WAV 格式
    
    Args:
        input_path: 输入文件 (mp3, m4a, etc.)
        output_path: 输出文件，None 则在同目录生成
        
    Returns:
        转换后的 WAV 路径，失败返回 None
    """
    if output_path is None:
        output_path = input_path.with_suffix(".wav")
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(output_path)
    ]
    
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if r.returncode == 0 and output_path.exists() and output_path.stat().st_size > 1000:
            return output_path
        else:
            print(f"    [transcribe] ffmpeg failed: {r.stderr.decode()[:100] if r.stderr else r.returncode}")
            return None
    except Exception as e:
        print(f"    [transcribe] ffmpeg error: {e}")
        return None
