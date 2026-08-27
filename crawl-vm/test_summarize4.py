#!/usr/bin/env python3
"""Test Groq summarization with longer text"""
import sys
sys.path.insert(0, '/home/ubuntu/.dsh/skills/crawl-vm')

# Load config directly
import yaml
with open('/home/ubuntu/.dsh/skills/crawl-vm/config.yaml') as f:
    config = yaml.safe_load(f)

from common.summarize import SummarizationService

svc = SummarizationService(config.get('summarization', {}))

# Longer text (over 300 chars)
test_text = """今天A股三大指数集体上涨，沪指涨1.5%，深成指涨2.0%，创业板指涨2.5%。科技股表现强劲，半导体板块领涨。成交额突破万亿关口，市场情绪明显回暖。

从盘面来看，今日三大指数高开高走，个股呈现普涨格局。半导体板块成为今日最大亮点，多只个股涨停。软件板块同样表现活跃，人工智能相关个股持续受到资金追捧。消费板块企稳回升，白酒股反弹明显。

资金面上，今日成交额突破万亿元大关，较昨日明显放量。北向资金大幅净流入，显示外资对A股市场信心增强。机构投资者表示，当前市场估值处于历史低位中长期配置价值凸显。

展望后市，分析师认为市场有望延续震荡上行态势。科技成长板块仍是主线，但需注意板块轮动节奏。低估值的消费金融板块存在补涨机会。操作上建议均衡配置，关注业绩确定性较高的优质标的。"""

print(f"Text length: {len(test_text)}")
result = svc.summarize(test_text)
print(f"Summary result: {result[:200] if result else 'EMPTY'}...")
