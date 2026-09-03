#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
common/transcribe.py — 音频转录模块 (拷贝自 crawl-vm, 含每条约耗时计时)

主路径: 直连 Groq (whisper-large-v3, 需 VPN 7890)
Fallback: 阿里云百炼 bailian (bl speech recognize, fun-asr 中文长录音 ASR)
"""
import json
import subprocess
import time as _time
from pathlib import Path
from typing import Optional


class TranscriptionService:
    def __init__(self, config: dict):
        self.model = config.get("model", "whisper-large-v3")
        self.proxy = config.get("proxy", "http://127.0.0.1:7890")
        self.language = config.get("language", "zh")
        self.groq_timeout = config.get("groq_timeout", 180)

        # 读 Groq Key (与 crawl-vm 同路径)
        self.groq_key = None
        groq_file = Path.home() / ".agents/credentials/ominicrawl/groq.json"
        if groq_file.exists():
            try:
                data = json.loads(groq_file.read_text())
                self.groq_key = data.get("api_key")
            except (json.JSONDecodeError, KeyError) as e:
                print(f"    [transcribe] Failed to read groq key: {e}")

    def transcribe(self, audio_path: Path) -> str:
        """转录音频文件 (主路径 Groq, fallback bailian)"""
        if not audio_path.exists() or audio_path.stat().st_size < 1000:
            return ""

        if self.groq_key:
            text = self._groq_transcribe(audio_path)
            if text:
                return text
            print(f"    [transcribe] Groq failed, trying bailian fallback...")

        text = self._bailian_transcribe(audio_path)
        if text:
            return text

        print(f"    [transcribe] All providers failed")
        return ""

    def _groq_transcribe(self, audio_path: Path) -> str:
        """直连 Groq whisper (需 VPN 127.0.0.1:7890)"""
        if not self.groq_key:
            return ""

        groq_model = self.model
        if groq_model in ("auto", "whisper-1"):
            groq_model = "whisper-large-v3"

        prompt = "Chinese, formal, with proper punctuation. 请用中文标点符号。"

        cmd = [
            "curl", "-s", "--proxy", self.proxy,
            "-X", "POST",
            "https://api.groq.com/openai/v1/audio/transcriptions",
            "-H", f"Authorization: Bearer {self.groq_key}",
            "-F", f"model={groq_model}",
            "-F", f"language={self.language}",
            "-F", f"file=@{audio_path}",
            "-F", f"prompt={prompt}",
            "-F", "response_format=text",
        ]

        t0 = _time.time()
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.groq_timeout)
            elapsed = _time.time() - t0
            if result.returncode == 0 and result.stdout.strip():
                text = result.stdout.strip()
                print(f"    [transcribe] Groq success: {len(text)} chars ({elapsed:.1f}s)")
                return text
            else:
                err = result.stderr[:100] if result.stderr else f"code={result.returncode}"
                if result.stdout:
                    err = result.stdout[:200]
                print(f"    [transcribe] Groq failed: {err} ({elapsed:.1f}s)")
                return ""
        except subprocess.TimeoutExpired:
            print(f"    [transcribe] Groq timeout ({_time.time() - t0:.1f}s)")
            return ""
        except Exception as e:
            print(f"    [transcribe] Groq error: {e} ({_time.time() - t0:.1f}s)")
            return ""

    def _bailian_transcribe(self, audio_path: Path) -> str:
        """阿里云百炼 ASR 兜底 (bl speech recognize, fun-asr)"""
        cmd = [
            "bl", "speech", "recognize",
            "--url", str(audio_path),
            "--language", self.language,
            "--output", "text",
        ]

        t0 = _time.time()
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            elapsed = _time.time() - t0
            if result.returncode == 0 and result.stdout.strip():
                text = result.stdout.strip()
                print(f"    [transcribe] bailian success: {len(text)} chars ({elapsed:.1f}s)")
                return text
            else:
                err = result.stderr[:200] if result.stderr else f"code={result.returncode}"
                if result.stdout:
                    err = result.stdout[:200]
                print(f"    [transcribe] bailian failed: {err} ({elapsed:.1f}s)")
                return ""
        except subprocess.TimeoutExpired:
            print(f"    [transcribe] bailian timeout ({_time.time() - t0:.1f}s)")
            return ""
        except Exception as e:
            print(f"    [transcribe] bailian error: {e} ({_time.time() - t0:.1f}s)")
            return ""


def convert_to_wav(input_path: Path, output_path: Path = None) -> Optional[Path]:
    """将音频文件转换为 WAV 格式 (16kHz mono pcm)"""
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