"""
common/ — subscription-crawl 共享模块包 (重构于 2026-07-08)

集中存放跨平台复用的代码: LLM 摘要(llm)、本地转录(transcribe)、
路径中枢(paths)、通用工具(util)、XHS 窗口管理(window)、
vault 发布(publish_vault)、订阅名单解析(feishu_watchlist, 已脱飞书读本地 vault)。

各平台脚本与各维护性脚本通过 `from common.xxx import ...` 复用本包,
使用前需保证 subscription-crawl 根目录(SKILL_DIR)已在 sys.path。
"""
