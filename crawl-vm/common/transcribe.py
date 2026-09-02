#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
common/transcribe.py — 音频转录模块

主路径: 直连 Groq (whisper-large-v3, 需 VPN 7890)
Fallback: 阿里云百炼 bailian (bl speech recognize, fun-asr 中文长录音 ASR)

Google Drive 文件下载 (gdown 依赖) 等不在本模块职责内。
"""
import json
import subprocess
import time as _time
from pathlib import Path
from typing import Optional

# ── record_timing bridge ─────────────────────────────────────────────────────
# 从 supervisor state 借 record_timing（VM 的 supervisor 运行在同一进程树，路径可达）
_SKILL_DIR = Path(__file__).resolve().parent.parent
_STATE_PY = _SKILL_DIR / "common_supervisor" / "state.py"
if _STATE_PY.exists():
    import sys
    _sup_dir = str(_SKILL_DIR / "common_supervisor")
    if _sup_dir not in sys.path:
        sys.path.insert(0, _sup_dir)
    try:
        from state import record_timing
    except Exception:
        record_timing = None
else:
    record_timing = None


class TranscriptionService:
    def __init__(self, config: dict):
        # 配置参数
        self.model = config.get("model", "whisper-large-v3")   # Groq 主路径模型
        self.proxy = config.get("proxy", "http://127.0.0.1:7890")  # Groq 需要的 VPN 代理
        self.language = config.get("language", "zh")
        self.groq_timeout = config.get("groq_timeout", 180)

        # 读 Groq cookie (主路径)
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

        # 主路径: Groq 直连
        if self.groq_key:
            text = self._groq_transcribe(audio_path)
            if text:
                return text
            print(f"    [transcribe] Groq failed, trying bailian fallback...")

        # Fallback: 阿里云百炼 (bl speech recognize, fun-asr)
        text = self._bailian_transcribe(audio_path)
        if text:
            return text

        print(f"    [transcribe] All providers failed")
        return ""

    def _groq_transcribe(self, audio_path: Path) -> str:
        """直连 Groq whisper (需 VPN 127.0.0.1:7890)

        Groq 接受的具体 model 名: whisper-large-v3, whisper-large-v3-turbo,
        distil-whisper-large-v3-en 等。
        """
        if not self.groq_key:
            return ""

        groq_model = self.model
        if groq_model in ("auto", "whisper-1"):
            groq_model = "whisper-large-v3"

        # Groq API 支持 prompt 参数引导 Whisper 添加标点
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
                if record_timing:
                    record_timing("transcribe_groq", elapsed, {"chars": len(text), "ok": True})
                return text
            else:
                err = result.stderr[:100] if result.stderr else f"code={result.returncode}"
                if result.stdout:
                    err = result.stdout[:200]
                print(f"    [transcribe] Groq failed: {err} ({elapsed:.1f}s)")
                if record_timing:
                    record_timing("transcribe_groq", elapsed, {"ok": False, "err": str(err)[:80]})
                return ""
        except subprocess.TimeoutExpired:
            elapsed = _time.time() - t0
            print(f"    [transcribe] Groq timeout ({elapsed:.1f}s)")
            if record_timing:
                record_timing("transcribe_groq", elapsed, {"ok": False, "err": "timeout"})
            return ""
        except Exception as e:
            elapsed = _time.time() - t0
            print(f"    [transcribe] Groq error: {e} ({elapsed:.1f}s)")
            if record_timing:
                record_timing("transcribe_groq", elapsed, {"ok": False, "err": str(e)[:80]})
            return ""

    def _bailian_transcribe(self, audio_path: Path) -> str:
        """阿里云百炼 ASR 兜底 (bl speech recognize, fun-asr)

        使用已安装的 bailian CLI (bl), 默认模型 fun-asr 支持中文长录音。
        """
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
                if record_timing:
                    record_timing("transcribe_bailian", elapsed, {"chars": len(text), "ok": True})
                return text
            else:
                err = result.stderr[:200] if result.stderr else f"code={result.returncode}"
                if result.stdout:
                    err = result.stdout[:200]
                print(f"    [transcribe] bailian failed: {err} ({elapsed:.1f}s)")
                if record_timing:
                    record_timing("transcribe_bailian", elapsed, {"ok": False, "err": str(err)[:80]})
                return ""
        except subprocess.TimeoutExpired:
            elapsed = _time.time() - t0
            print(f"    [transcribe] bailian timeout ({elapsed:.1f}s)")
            if record_timing:
                record_timing("transcribe_bailian", elapsed, {"ok": False, "err": "timeout"})
            return ""
        except Exception as e:
            elapsed = _time.time() - t0
            print(f"    [transcribe] bailian error: {e} ({elapsed:.1f}s)")
            if record_timing:
                record_timing("transcribe_bailian", elapsed, {"ok": False, "err": str(e)[:80]})
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