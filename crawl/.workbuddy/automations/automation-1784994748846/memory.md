# 自动化执行记录：每日执行crawl爬取 (automation-1784994748846)

## 2026-08-12 16:56–17:00 (UTC+8)
- 命令：`./run.sh all`（crawl 3.1.0 全流程：watchlist → clip → report）
- 结果：**成功**，退出码 0，墙钟 4.3min
- run_tag：`run_20260812_165600_44557`
- 三阶段均正常：watchlist 落库 8 篇 + handoff VM 1；clip 无链接结束；OP 报告已生成
- 本批新增（本地）：小红书 3（基金大佬简报/半导体设备/实盘汇总）、京东 1（多平台比价）、贴吧 4（少年西游记）
- VM 异步转录：bilibili 13 + douyin 8 = 21 篇，全部成功（FunASR+Zhipu，daemon 当天累计）
- 健康检查发现 3 个非阻断 WARN：douyin.json 缺失(备用)、Bailian smoke 异常(name 'shutil' 未定义,极简模式已 disable 不影响)、Chrome 扩展一度断开后恢复
- 注意：truth.json 中的 22 条 error 均为历史 recovery 残留（旧时间戳 20:44/20:47/20:00/00:09），本次 run 的 groq_429=0、asr_fatal=0，实际无新增错误
- 产出文件：`/Users/tianwenliang/Documents/steven_vault/04_agent/report/crawl_op_20260812.md`
