#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
common/summarize.py — 文本总结模块

使用 Groq LLM 进行文本总结
"""
import json
import subprocess
from pathlib import Path
from typing import Optional


class SummarizationService:
    def __init__(self, config: dict):
        self.model = config.get("model", "qwen/qwen3.8-27b")
        self.proxy = config.get("proxy", "http://127.0.0.1:7890")
        self.max_tokens = config.get("max_tokens", 1024)
        self.temperature = config.get("temperature", 0.3)
        self.min_chars = config.get("min_chars", 300)
        
        # 读取 API Key
        self.api_key = self._load_api_key()
    
    def _load_api_key(self) -> str:
        """加载 Groq API Key"""
        key_file = Path.home() / ".agents/credentials/ominicrawl/groq.json"
        if key_file.exists():
            try:
                return json.loads(key_file.read_text())["api_key"]
            except (json.JSONDecodeError, KeyError):
                pass
        
        import os
        return os.environ.get("GROQ_API_KEY", "")
    
    def summarize(self, text: str, max_len: int = 500) -> str:
        """总结文本
        
        Args:
            text: 输入文本
            max_len: 最大输出长度
            
        Returns:
            总结文本
        """
        if not text or len(text) < self.min_chars:
            return ""
        
        if not self.api_key:
            print(f"    [summarize] Groq API key not found")
            return ""
        
        prompt = f"""请用简洁的语言总结以下内容的核心要点，字数控制在{max_len}字以内：

{text[:3000]}

总结："""
        
        messages = [
            {"role": "user", "content": prompt}
        ]
        
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        
        # 使用 curl 调用 Groq API
        cmd = [
            "curl", "-s", "--proxy", self.proxy,
            "-X", "POST",
            "https://api.groq.com/openai/v1/chat/completions",
            "-H", "Content-Type: application/json",
            "-H", f"Authorization: Bearer {self.api_key}",
            "-d", json.dumps(payload),
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0 and result.stdout.strip():
                resp = json.loads(result.stdout)
                if "choices" in resp and len(resp["choices"]) > 0:
                    summary = resp["choices"][0]["message"]["content"].strip()
                    print(f"    [summarize] Success: {len(summary)} chars")
                    return summary
            
            print(f"    [summarize] Failed: {result.stdout[:100] if result.stdout else result.stderr[:100]}")
            return ""
        except json.JSONDecodeError:
            print(f"    [summarize] Invalid JSON response")
            return ""
        except Exception as e:
            print(f"    [summarize] Error: {e}")
            return ""
    
    def summarize_simple(self, text: str) -> str:
        """简单总结（不做字数限制）"""
        return self.summarize(text, max_len=300)
