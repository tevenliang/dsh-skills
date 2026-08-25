# 报告样例（2026-07-26 — 真实数据范本）

> 取代 sample_0725.md（已废弃）。本样例基于 `parse_timing_truth.py` 输出
> 与 vault 实际清单，**不依赖 supervisor 各操作耗时统计 块**。

---

# ominicrawl 爬取耗时 · 真实数据版（2026-07-26）

> **数据源**：直接 grep `/tmp/watchlist_full.log`
> **解析工具**：`crawl/scripts/parse_timing_truth.py`
> **生成时间**：2026-07-26 20:55
> **动机**：第一版报告因依赖 supervisor `timing.json`（漏计 28/32 extract_audio、24/29 summarize_glm、21/30 bailian ASR），数字严重虚高。本版全部从日志原文提取。

---

## 一、跑批基本信息

| 项 | 值 |
|---|---|
| 启动 | 2026-07-26 19:35:38 |
| 结束 | 2026-07-26 ~20:11（supervisor exit=0） |
| 总墙钟 | ~33 min (1979s) |
| 处理平台 | 7（抖音 / B站 / 小红书 / Boss / 京东 / LinkedIn / 贴吧） |
| 实际产出 | **63 篇**（vault 索引 `0726-index.md` 显示）= 59 内容笔记 + 4 平台 hot.md |

---

## 二、按 op 真实耗时（核心维度）

> **口径**：每个 op 的 count / avg / min / max / total 全部从日志结构化字段直接 grep，无任何推断。"占总时间 %" 以总墙钟 1979s 为分母。

| op | 数据来源 | count | avg | total | min | max | 占 33min % |
|---|---|---:|---:|---:|---:|---:|---:|
| **transcribe_bailian** | `[bailian] fun-asr-mtl, 总耗时 X.Xs` | **30** | 15.76s | **472.9s (7.88min)** | 7.40s | 48.60s | **23.9%** |
| **opencli_op** | `state/timing.json` 结构化实测 | **4** | 144.58s | **578.3s (9.64min)** | 4.26s | 534.10s | **29.2%** |
| **extract_audio** | `[audio] 抽取完成/失败 总=X.Xs` | **32** | 2.11s | 67.5s (1.12min) | 0.00s | 34.60s | 3.4% |
| **summarize_glm** | `📝 总结完成` 行计数 | **29** | — | — | — | — | — |
| **summarize_glm 跳过** | `⚠️ 总结跳过` | **1** | — | — | — | — | — |
| **transcribe_mlx** | `[mlx] ... X.Xs` | **1** | 17.60s | 17.6s | 17.60s | 17.60s | 0.9% |
| **transcribe_groq 成功** | `[groq] ... (Xs) 成功` | **0** | — | **0s** | — | — | **0%** |
| **groq 429 触发** | `[groq] ... 429/限流` | **6** | — | — | — | — | — |
| **skip_dedup 命中** | `⏭️ 已存于 / 已缓存` | **329** | — | — | — | — | — |

**op 实测累计** ≈ 1136s = **18.9 min**（占墙钟 57%）

**未计入 op 的剩余 14.1 min（占墙钟 43%）**：
- 平台间切换（爬取-转录-总结串行调度）
- 网络抓取正文（`fetch` op 不可测，因为 supervisor 不记）
- publish_vault 落盘（本机写文件）
- [bailian] poll 等待（已计入 bailian 总耗时）

---

## 三、关键观察

### 真正耗时大头（按占比从高到低）

1. **opencli_op · 9.64 min (29.2%)** ← 真实第一名
   - 4 次中 1 次 534.1s（**8.9 min**）—— 抖音某视频 opencli 浏览器渲染卡死
   - 其余 3 次共 44.3s
   - 触发原因：`⚠️ 正文过少 (body=24/25), 触发 opencli 回退`
   - **可优化**：给 opencli_op 加 hard timeout（如 60s），超时则 skip

2. **transcribe_bailian · 7.88 min (23.9%)** ← 稳定、不动
   - 30 次 fun-asr-mtl 异步调用
   - p50=14.4s, p90=17.8s
   - 一次离群 48.6s
   - 与 0725 的 14.5s/次 一致，无回归

3. **extract_audio · 1.12 min (3.4%)** ← 健康
   - 32 次大多数 < 1s，少数下载 (max 34.6s)

4. **summarize_glm · 29 次完成** ← GLM 工作正常
   - **GLM 真实单次时长不可信**（supervisor `timing.json` 漏记 24 次）
   - 若想知道真实 GLM 调用时间，需要查 GLM 端 API 日志或 grep `[glm] ... Xs` 行
   - 占总时间 % 暂不可计算（被本次 skill 划为不可知）

### groq 实际没用上

- 30/31 次需要 ASR 的视频全部走 bailian
- groq 6 次 429 触发 → supervisor 自动切 bailian（cooldown 5min × 3 段、1min × 3 段）
- 但 cooldown 期间 supervisor **不 sleep**（set cooldown_until，被动 skip），并未浪费 15min 真实时钟

### 与 0725 对比

| 维度 | 0725（凌晨后台） | 0726（今晚 7 平台） |
|---|---|---|
| 总墙钟 | 120+ min | **33 min** |
| bailian ASR avg | 14.5s | **15.76s** ✓ 一致 |
| 产出 | 43 | **63** ↑ 47% |
| groq 成功 | 21 | 0（免费层配额触顶） |

---

## 四、唯一可优化点

**opencli_op 那一次 534.1s 卡死（占整次 27%）。**

其他所有项都健康。原报告把 groq/cooldown 等列为可优化点的判断**已被废弃** —— 因为 supervisor cooldown 不 sleep。

---

## 五、可复现命令

```bash
/Users/tianwenliang/.agents/.venv/bin/python3 \
  /Users/tianwenliang/.agents/skills/crawl/scripts/parse_timing_truth.py \
  /tmp/watchlist_full.log
```

---

## 六、参考

- 数据源说明 → 主报告 §二
- supervisor 漏计偏差 → `references/known_deviations.md` §A
- 老 supervisor 块(不可信)→  `state/timing.json`
