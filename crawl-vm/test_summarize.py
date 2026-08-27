#!/usr/bin/env python3
"""测试 Groq 总结"""
import sys
sys.path.insert(0, '/home/ubuntu/.dsh/skills/crawl-vm')
from common.summarize import SummarizationService
from pathlib import Path

config = {
    "model": "llama-3.1-70b-versatile",
    "proxy": "http://127.0.0.1:7890",
    "max_tokens": 200,
    "temperature": 0.3,
    "min_chars": 50,
}

svc = SummarizationService(config)
test_text = "今天A股三大指数集体上涨，沪指涨1.5%，深成指涨2.0%，创业板指涨2.5%。科技股表现强劲，半导体板块领涨。成交额突破万亿关口，市场情绪明显回暖。"

result = svc.summarize(test_text)
print(f"Summary: {result}")
