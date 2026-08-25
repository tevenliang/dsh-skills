# 已知测量偏差（重要）

> 本文件列出 ominicrawl supervisor 日志中**已知的数据失真点**。
> 写报告时务必把这些失真**显式标注**，否则用户会按真实耗时理解、误判优化方向。

---

## A. ⭐ 2026-07-26 新发现：supervisor 各操作耗时统计块 + state/timing.json 严重漏计

**这是最严重的数据问题**。今天 0726 跑批发现:

| op | parse_timing_truth (真实) | supervisor block (各操作耗时统计) | supervisor timing.json | 漏计% |
|---|---:|---:|---:|---:|
| extract_audio | 32 次 | (未列出) | 4 次 | **漏 87%** |
| transcribe_bailian | 30 次 | (未列出) | 9 次 | **漏 70%** |
| summarize_glm | 29 次 | (未列出) | 5 次 | **漏 82%** |

**根因**:
- supervisor 的 `_record_op_direct` 是在**结构化事件出现时逐一记录**(基于 `_start_op`/`_finish_op` 状态机)
- 但某些 op(如 summarize_glm)内部用 LLM 调用内部 `time.time()` 实测,supervisor 看到的只是 `📝 总结完成` 这一行,**没有拿到耗时**
- 当 supervisor 怀疑自己在补捉 op 边界时,就走 gap 计时(上一个 _active_op 结束 = 下一个开始),但因为 op 间的边界线对不上,结果就是"重复"或"漏记"

**实际行为**(以 extract_audio 为例):
- 日志里 32 次打印 `[audio] 抽取完成 下载=Xs 转码=Ys 总=X.Xs`(实测,正确)
- 但 supervisor 只在**第一次** extract_audio 之后调用 `_record_op_direct`,后续 31 次没记
- 但 supervisor 又会基于 "fast-path skip" 让一些 ASR 不进 timing.json
- 加起来,supervisor 看到的 op 序列不连续,导致部分 op 被吞

**规则**:
- 报告**永远不要相信 supervisor 块的 count**
- 报告**也不要相信 timing.json 的 count**
- op 的所有数字必须从日志原文 grep 出来
- avg/min/max 是合理的(只要 count 对),如果 count 错 avg 就被错基数算出错误的"平均"

---

## B. extract_audio 计时起点过早（旧版本，已修复）

**现象**：`extract_audio total` 看起来特别大（0725 实测 133min），但实际下载+转码不应这么慢。

**根因**：旧 supervisor 的 `_parse_timing_from_line` 从 `[audio] X MB, Ys` 这一行开始计时——也就是打印"抽取完成"那行。但 `[audio] 抽取完成` 是抽取**之后**的输出行。真正耗时在它**之前**,所以被计入的不是真实等待。

**已修**: 2eb7067 commit（instrumentation 精准计时）。新版本 `_record_op_direct("extract_audio", float(m.group(4)))` 直接读日志原文 `[audio] 抽取完成 总=X.Xs` 字段实测。

**报告应注**: `parse_timing_truth.py` 已从 `[audio] 总=X.Xs` 字段拿值,无需担心。但旧版本 supervisor 块的 extract_audio avg 仍可能过大（如果回归）。

---

## C. extract_audio 与 transcribe_groq 计时区间相邻/重叠

**现象**：0725 extract_audio 133min 与 transcribe_groq 130min 几乎相等。

**根因**：旧版本 supervisor 是「链式 gap」——上一 op 结束 = 下一 op 开始。

- extract_audio 在 `[audio] X MB` 处结束
- transcribe_groq 紧接着从同一行的下一次出现开始

两个 op 中间网络等待/解析/异常 fallback 时间被双重计入。

**报告应注**：这是历史测量层面的边界效应，从 `parse_timing_truth.py` 输出不存在此问题。

---

## D. B站"下载=0s"是设计预期

`bili_feed._audio_download_with_retry` 在 `extract_audio_to_wav` 之前就预下载完,`[audio] 抽取完成 下载=0.0s` 是预期,不是卡顿。

**报告应注**: 不在报告里标记为异常。

---

## E. opencli_op 单次超时（0726 实测）

**现象**: 0726 实测 1 次 534.1s（抖音某视频）。

**性质**: opencli 浏览器渲染的固有问题，**不是 bug**——但**确实是唯一一个可优化点**（加 hard timeout）。

**报告应注**: 必须明确指出。当 opencli_op max > 60s 时建议加 hard timeout。

---

## F. groq 429 / cooldown 期间 supervisor 不浪费真实时钟

**重要推翻**：原报告里"groq 5min cooldown 浪费 X% 总时间"是 **错**的。

supervisor 在 cooldown 期间**不 sleep**:
- `set_provider_cooldown("groq", 300)` 设 cooldown_until
- 下一条 ASR 请求进来，supervisor 查 cooldown_until，没过就 `skip (recovery: disabled by supervisor)`
- supervisor 不 sleep，所以不影响真实时钟

**报告应注**: 不要再写"groq 浪费 X% 冷却时间"。

---

## G. fetch op（网络正文抓取）不可计时

supervisor 的 OP_PATTERNS 只识别 bilibili/douyin/xiaohongshu 的网络抓取,但**没有为它们注册 op**(只有 match,没有 _record_op_direct)。

所以 fetch 时间只能通过 `[N/7]` 进度行的"本阶段"差额推算,精度为分钟级。

**报告应注**: 平台阶段耗时表允许"分钟精度"。
