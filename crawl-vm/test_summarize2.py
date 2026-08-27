#!/usr/bin/env python3
"""Test Groq summarization with proper config"""
import sys
sys.path.insert(0, '/home/ubuntu/.dsh/skills/crawl-vm')

# Load config directly
import yaml
with open('/home/ubuntu/.dsh/skills/crawl-vm/config.yaml') as f:
    config = yaml.safe_load(f)

print(f"Config summarization: {config.get('summarization', {})}")

from common.summarize import SummarizationService

svc = SummarizationService(config.get('summarization', {}))
print(f"Model: {svc.model}")
print(f"API Key: {svc.api_key[:20] if svc.api_key else 'EMPTY'}...")

test_text = "今天A股三大指数集体上涨，沪指涨1.5%，深成指涨2.0%，创业板指涨2.5%。科技股表现强劲，半导体板块领涨。成交额突破万亿关口，市场情绪明显回暖。"

result = svc.summarize(test_text)
print(f"Summary: {result}")
