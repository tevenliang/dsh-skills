# crawl 项目 — 全流程隐藏 Bug 深度评审报告

**评审日期**: 2026-08-18  
**评审方法**: 从 run.sh → supervisor.py → crawl.py → publish_vault.py → handoff_vm.py → transcribe_daemon.py → transcribe_worker.py → common-asr/transcribe.py **逐行追踪完整数据流**  
**范围**: ~200 个文件，约 26,000 行 Python + Shell

---

## 🔴 BUG-009B [CRITICAL]: sys.path 导入冲突 —— 你所有问题的根因

**影响**: **每次爬取都会用旧版代码而不是你期望的新版代码**

### 证据链

`crawl.py` (common-flow/crawl.py) 启动时注入 sys.path:
```python
for _p in (str(SKILL_DIR), str(SKILL_DIR / "common"), str(SKILL_DIR / "tools"), ...):
    if _p not in sys.path:
        sys.path.insert(0, _p)
```

然后导入:
```python
from common.publish_vault import append_single_to_hot  # ← 找 common/publish_vault.py!
```

但你的 **最新版本在 `common-publish/publish_vault.py`**（那个带 `_materialize_images_xhs_fallback`、图片 wikilink 改写等逻辑的版本）。

因为 `sys.path` 里 `"common"` 排在 `"common-publish"` 前面，Python 先找到旧版 `common/publish_vault.py` —— 而这个旧版 **没有** 你在后续修复中加的所有改进。

### 同样的问题在所有 common-* 模块都存在:

| 功能 | 旧版位置（实际被导入） | 新版位置（你想要的） |
|------|---------------------|-------------------|
| publish_vault | `common/publish_vault.py` | `common-publish/publish_vault.py` |
| summarize | `common/summarize.py` | `common-summary/summarize.py` |
| transcribe | `common/transcribe.py` | `common-asr/transcribe.py` |
| pipeline/run | `pipeline/run.py` | `common-flow/pipeline/run.py` |
| jobqueue | `pipeline/jobqueue.py` | `common-flow/pipeline/jobqueue.py` |

**这就是为什么你反复说"总结格式不对""vault-summary 没用上""转录质量差"——因为你看到的运行时的代码根本不是最新的版本！**

---

## 🔴 BUG-003 [HIGH]: VM Worker 的 vault-summary 路径不存在且无检查

**文件**: `vm/transcribe_worker.py` Line 52

```python
VAULT_SUMMARY_SCRIPT = Path.home() / ".hermes" / "skills" / "codex" / "PRODUCTIVITY" / "vault-summary" / "scripts" / "summarize_file.py"
```

**问题**：
1. 这个路径通过 `vm-skills-push` 推送到 VM，但推送可能失败/延迟
2. worker 里没有 `.exists()` 检查
3. subprocess 找不到文件 → FileNotFoundError → catch Exception → fallback to GLM
4. 你说百炼额度已耗尽 → GLM 也调不通 → **整个总结返回空或极短文本**

---

## 🔴 BUG-001 [HIGH]: FunASR 模型单例会导致 OOM

**文件**: `vm/transcribe_worker.py`

虽然当前 daemon 串行执行所以不会炸，但如果将来改为并发处理：
- FunASR 加载 ≈ 1.2GB
- VM 只有 3.6GB 内存
- 两个 worker 同时启动 → OOM → 转录崩溃

---

## 🟡 BUG-002 [MODERATE]: handoff copy 非原子操作

**文件**: `tools/handoff_vm.py` Line 112

```python
shutil.copy2(wav_path, wav_tmp)  # ← copy 不是 move！
```

上传成功后只删了 `wav_tmp`，原始 `wav_path` 留在 Mac 本地。偶发产生"孤儿 wav"不会被 backfill 发现。

---

## 🟡 BUG-004 [MODERATE]: ActionMonitor 依赖正则匹配进度行

**文件**: `common_supervisor/supervisor.py` Line 79-86

如果爬虫框架更新输出格式（去掉 ETA、改括号符号），正则不匹配 → `touch(None)` 直接 return → ActionMonitor 认为进度不变 → grace_sec 超时后误杀进程。

grace_sec 已从 600s 调到 1800s 缓解，但没根治。

---

## 🟡 BUG-005 [MODERATE]: vault 同步延迟导致重复爬取

**文件**: `common-flow/crawl.py` `_md_is_complete`

Mac 端扫 `~/Documents/steven_vault/subscription/` 判断视频是否已处理。但如果 Obsidian Remotely Save 还没同步回来，同一个视频可能被重新抓取。

---

## 🟡 BUG-006 [MODERATE]: hot.md 读写竞争

**文件**: `common-publish/publish_vault.py` `_update_hot_index`

read-modify-write 模式：多进程并发写入会互相覆盖。当前串行没问题，但未来并行化就是隐患。

---

## 🟢 BUG-007 [LOW]: proxy bypass 行为未文档化

**文件**: `common-asr/transcribe.py`

对 B站 upos CDN 绕过代理直连提速。特定网络环境下可能导致失败，调试时容易困惑。

---

## 📊 漏洞矩阵

| 编号 | 名称 | 严重度 | 频率 | 修复难度 |
|------|------|--------|------|---------|
| 009B | sys.path 新旧代码混用 | 🔴 CRITICAL | **每次爬取** | 低 |
| 003 | vault-summary 路径无存在性检查 | 🔴 HIGH | **每次 VM 转录** | 低 |
| 001 | FunASR 内存风险 | 🔴 HIGH | 并发时 | 低 |
| 002 | handoff copy 非原子 | 🟡 MODERATE | 偶发 | 低 |
| 004 | ActionMonitor 正则脆弱 | 🟡 MODERATE | 偶发 | 中 |
| 005 | vault 同步延迟重爬 | 🟡 MODERATE | 偶发 | 低 |
| 006 | hot.md 竞争写入 | 🟡 MODERATE | 并发时 | 低 |
| 007 | proxy bypass 未文档化 | 🟢 LOW | 特定网络 | 低 |

---

## 🎯 推荐修复优先级

### Phase 1 — 立即（立竿见影）

**1. 修复 sys.path 导入冲突** ⭐⭐⭐
   - 确认哪些 `common/*.py` 是冗余副本
   - 让所有 import 指向正确的 `common-*` 目录下的新版本
   - 预计: 1小时
   - **效果**: 保证所有调用都使用最新代码

**2. 添加 vault-summary 存在性检查** ⭐⭐
   ```python
   def summarize(text: str) -> str:
       if not VAULT_SUMMARY_SCRIPT.exists():
           print("[worker] vault-summary 不存在", flush=True)
           return ""  # 走 GLM fallback
   ```
   - 预计: 10分钟

**3. 验证 FunASR punct_model 状态** ⭐⭐
   - 检查 `transcribe_worker.py` model loaded 日志
   - 确认标点模型是否正常加载（FunASR 不需要 prompt 加标点，punc_model 自带）

### Phase 2 — 本周

4. handoff 改为 move 而非 copy
5. hot.md 写加文件锁
6. ActionMonitor 加 debug 日志
7. vault sync 状态检查

### Phase 3 — 长期

8. 消除 common/ 和 common-* 的重复结构
9. 补充 unittest
10. CI pipeline

---

*End of Review*
