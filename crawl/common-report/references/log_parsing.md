# supervisor 日志解析手册（2026-07-26 修订版）

> ⚠️ **重要**：本手册不再以 `各操作耗时统计:` 块作为 op 数据源（漏计严重）。
> **唯一可信 op 数据源** = `parse_timing_truth.py` 直接 grep 日志原文。
>
> 但**平台入站/出站时间**仍可信（supervisor 进度行是 `[N/7]` 准的），用于报告二段。

---

## 1. 启动时间

```
grep -m1 "Supervisor.*启动" <log>
```
或：
```
grep -m1 "启动 PID=" <log>
```
日期从文件路径 `run_YYYYMMDD.log` 拿，或从 supervisor `state/supervisor.json` 拿。

---

## 2. 各平台入站时间点（可信）

```
grep -E "进入平台:" <log>
```
示例：
```
[1/7] 进入平台: 抖音  (已用时 0s)
[2/7] 进入平台: B站  (已用时 10min)
```

---

## 3. supervisor 进度条（可信，仅用于分钟精度）

```
grep -E "\[[1-7]/7\]" <log> | grep "总计"
```
示例：
```
[1/7] 抖音 › 帽子哥聊财经  0/5 (0%)  | 本阶段 5min  | 总计 5min
```

---

## 4. ⭐ op 真实耗时（用 parse_timing_truth.py，不要手动 grep）

**首选**：
```bash
/Users/tianwenliang/.agents/.venv/bin/python3 \
  /Users/tianwenliang/.agents/skills/crawl/scripts/parse_timing_truth.py \
  <log_path>
```

**手工核对用（参考）**：

| op | grep 模式 |
|---|---|
| `extract_audio` | `[audio] 抽取完成/失败 总=([\d.]+)s` |
| `transcribe_bailian` | `fun-asr-mtl, 总耗时 ([\d.]+)s` |
| `transcribe_groq` | `\[groq\].*成功.*?([\d.]+)s` |
| `transcribe_mlx` | `\[mlx.*\].*?([\d.]+)s` |
| `summarize_glm` | `📝 总结完成`（行数即 count，无秒数） |
| `summarize_glm 跳过` | `⚠️ 总结跳过`（行数即 count） |
| `groq 429 触发` | `\[groq\].*(?:429\|限流)` |
| `skip_dedup 命中` | `⏭️.*已存于\|⏭️.*已缓存\|⏭️ dedup` |
| `opencli_op` | 仅 supervisor state/timing.json（这里漏计少，可信） |

**别用的模式**（不可信）：
- `各操作耗时统计:` 块（漏计 70-87%）
- `state/timing.json` 同上
- `supervisor` 自打印的任何 op count

---

## 5. bailian 实际执行次数

```
grep -c "fun-asr-mtl, 总耗时" <log>   # 不算失败
grep -c "bailian.*task_id=" <log>     # 包含失败/重试
```

---

## 6. groq 限流次数

```
grep -c "groq.*429\|groq.*额度限流" <log>          # 429 触发
grep -c "groq ⏭️ 跳过 (recovery: disabled)" <log>  # supervisor 跳过
```

---

## 7. 实际产出（vault 新增笔记数）

**推荐用 mmin 而非 mtime**（macOS BSD find 没有 -newer 选项稳定）：
```bash
find "$VAULT/subscription" -type f -name "*.md" -mmin -120 | wc -l
```

按子目录分布：
```bash
for plat in douyin bilibili xiaohongshu boss jd linkedin tieba; do
  cnt=$(find "$VAULT/subscription/$plat" -type f -name "*.md" -mmin -120 2>/dev/null | wc -l)
  echo "  $plat/ → $cnt"
done
```

按日期精确（覆盖跨夜跑批）：
```bash
find "$VAULT/subscription" -type f -name "YYYY-MM-DD_*" | wc -l
```

---

## 8. 总结执行次数

```
grep -c "📝 总结完成:" <log>      # 完成数
grep -c "⚠️ 总结跳过:" <log>     # 跳过数
```

**注**：GLM 单次**实际时长不可从这里拿**。supervisor `timing.json` 在 summarize_glm 这一项**严重漏计**(实证: 29 次只记 5 次)。

如要 GLM 单次真实时长，需要：
1. GLM 后端 API 日志（如有商业套餐）
2. 或 grep `[glm] ... 用时 X.Xs` 这种 GLM 自带秒数的行（**前提是原始 `[glm] 完成` 行带耗时字段，需查 common-summary 代码确认**）

---

## 报告 CSV 化（一次性整合）

```bash
grep -oE "fun-asr-mtl, 总耗时 [0-9.]+s" <log> | grep -oE "[0-9.]+" > bailian_times.txt

python3 -c "
with open('bailian_times.txt') as f:
    times = [float(x) for x in f.read().split()]
print(f'n={len(times)} avg={sum(times)/len(times):.1f}s max={max(times):.1f}s')
"
```

---

## 已知 grep 陷阱

1. **不要信任 `各操作耗时统计` 块的 count** —— 见 §A known_deviations.md
2. **grep `groq ⏭️ 跳过`** 可能匹配到 `groq.*限流` 提示行，需要 `grep -v` 滤除
3. **多进程日志** —— 大批量时可能 supervisor 启动多个 worker，日志会有竞争。简单爬取（watchlist）一般单进程 OK。
4. **bailian 字符 "总耗时 Xs" 在 supervisor 块里也有** —— grep `fun-asr-mtl, 总耗时` 加前缀过滤即可
