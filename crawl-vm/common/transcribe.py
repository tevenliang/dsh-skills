#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
common/transcribe.py — 音频转录模块

主路径: freellmapi (localhost:31415) - 多 provider auto-router (groq whisper / cloudflare whisper / etc.)
Fallback: 直连 Groq (需要 VPN) - 仅当 freellmapi 不可达时启用

为什么优先 freellmapi:
1. 自动 provider failover: Groq 额度耗尽自动切 Cloudflare Workers AI whisper
2. 多 key 轮询: 不必担心单 key 429
3. 不需要 VPN: freellmapi 本身已配 PROXY_URL=http://127.0.0.1:7890 调境外 API
"""
import json
import subprocess
import urllib.request
import urllib.error
import urllib.parse
import mimetypes
from pathlib import Path
from typing import Optional


class TranscriptionService:
    def __init__(self, config: dict):
        # 配置参数
        self.model = config.get("model", "whisper-1")          # freellmapi 推荐 "whisper-1" / "auto"
        self.proxy = config.get("proxy", "http://127.0.0.1:7890")  # freellmapi 不可达时 fallback 用
        self.language = config.get("language", "zh")
        self.freellmapi_timeout = config.get("freellmapi_timeout", 120)
        self.fallback_to_groq = config.get("fallback_to_groq", True)

        # 读 freellmapi cookie (key + base_url)
        self.freellmapi_key = None
        self.freellmapi_base = "http://127.0.0.1:31415/v1"
        key_file = Path.home() / ".agents/credentials/ominicrawl/freellmapi.json"
        if key_file.exists():
            try:
                data = json.loads(key_file.read_text())
                self.freellmapi_key = data.get("api_key")
                self.freellmapi_base = data.get("base_url", self.freellmapi_base)
            except (json.JSONDecodeError, KeyError) as e:
                print(f"    [transcribe] Failed to read freellmapi key: {e}")

        # 读 Groq cookie (fallback)
        self.groq_key = None
        groq_file = Path.home() / ".agents/credentials/ominicrawl/groq.json"
        if groq_file.exists():
            try:
                data = json.loads(groq_file.read_text())
                self.groq_key = data.get("api_key")
            except (json.JSONDecodeError, KeyError) as e:
                print(f"    [transcribe] Failed to read groq key: {e}")

    def transcribe(self, audio_path: Path) -> str:
        """转录音频文件 (主路径 freellmapi, fallback Groq)"""
        if not audio_path.exists() or audio_path.stat().st_size < 1000:
            return ""

        # 主路径: freellmapi (优先)
        if self.freellmapi_key:
            text = self._freellmapi_transcribe(audio_path)
            if text:
                return text
            print(f"    [transcribe] freellmapi failed, trying Groq fallback...")

        # Fallback: Groq 直连
        if self.fallback_to_groq and self.groq_key:
            text = self._groq_transcribe(audio_path)
            if text:
                return text

        print(f"    [transcribe] All providers failed")
        return ""

    def _freellmapi_transcribe(self, audio_path: Path) -> str:
        """通过 freellmapi localhost:31415 转录

        freellmapi 内部 router 自动选 provider (groq whisper / cloudflare whisper)
        - POST /v1/audio/transcriptions with model=auto
        - 返回 {"text": "..."}
        """
        url = f"{self.freellmapi_base}/audio/transcriptions"
        # freellmapi router 推荐 "auto", "whisper-1" 在某些 routing 状态下会 502 (router 内部错误)
        model = "auto"

        try:
            # 用 Python urllib (避免 curl subprocess 依赖)
            boundary = "----FormBoundary" + str(hash(audio_path) & 0xFFFF)
            with open(audio_path, 'rb') as f:
                audio_data = f.read()

            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{audio_path.name}"\r\n'
                f"Content-Type: {mimetypes.guess_type(str(audio_path))[0] or 'audio/wav'}\r\n\r\n"
            ).encode() + audio_data + (
                f"\r\n--{boundary}\r\n"
                f'Content-Disposition: form-data; name="model"\r\n\r\n{model}\r\n'
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="language"\r\n\r\n{self.language}\r\n'
                f"--{boundary}--\r\n"
            ).encode()

            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Authorization": f"Bearer {self.freellmapi_key}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Content-Length": str(len(body)),
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.freellmapi_timeout) as resp:
                data = json.loads(resp.read())
                if "text" in data and data["text"]:
                    print(f"    [transcribe] freellmapi success: {len(data['text'])} chars (model={model})")
                    return data["text"]
                elif "error" in data:
                    print(f"    [transcribe] freellmapi error: {data['error'].get('message', '?')[:100]}")
                    return ""
                print(f"    [transcribe] freellmapi empty response")
                return ""
        except urllib.error.URLError as e:
            print(f"    [transcribe] freellmapi connection error: {str(e)[:100]}")
            return ""
        except (json.JSONDecodeError, KeyError) as e:
            print(f"    [transcribe] freellmapi parse error: {e}")
            return ""
        except Exception as e:
            print(f"    [transcribe] freellmapi error: {str(e)[:100]}")
            return ""

    def _groq_transcribe(self, audio_path: Path) -> str:
        """直连 Groq whisper (需 VPN) - freellmapi 不可达时的 fallback

        Groq 接受的具体 model 名: whisper-large-v3, whisper-large-v3-turbo,
        distil-whisper-large-v3-en 等 (不能用 "auto" 或 "whisper-1", 这些是 freellmapi 抽象名)
        """
        if not self.groq_key:
            return ""

        # 如果 config 里 model 是 freellmapi 抽象名, fallback 时换成 Groq 自己的 model
        groq_model = self.model
        if groq_model in ("auto", "whisper-1"):
            groq_model = "whisper-large-v3"  # Groq fallback 默认

        # Groq API 支持 prompt 参数引导 Whisper 添加标点
        prompt = "Chinese, formal, with proper punctuation. 请用中文标点符号。"

        # 调用 Groq API
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

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if result.returncode == 0 and result.stdout.strip():
                text = result.stdout.strip()
                print(f"    [transcribe] Groq fallback success: {len(text)} chars")
                return text
            else:
                err = result.stderr[:100] if result.stderr else f"code={result.returncode}"
                print(f"    [transcribe] Groq fallback failed: {err}")
                return ""
        except subprocess.TimeoutExpired:
            print(f"    [transcribe] Groq fallback timeout")
            return ""
        except Exception as e:
            print(f"    [transcribe] Groq fallback error: {e}")
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
