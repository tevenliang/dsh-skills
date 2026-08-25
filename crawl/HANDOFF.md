# HANDOFF — crawl 3.1.0 Mac→VM 转录交接

> 操作手册。代码改动见 `CHANGELOG.md`；设计/进度见 `ominicrawl/crawl-3.1.0-{design,progress}.md`。

## 拓扑

```
Mac (ominicrawl skill)
  └─ ingest-{bilibili,douyin}: 下载音频 → handoff_vm.py ──rsync over SSH──┐
                                                                          ▼
                                          VM 175.178.210.156:/home/ubuntu/crawl-transcribe/inbox/
                                                                          │  daemon (systemd crawl-transcribe) 30s 轮询
                                                                          ▼
                                          transcribe_worker.py: FunASR 转录 → Zhipu 总结 → publish_vault 写 vault
                                                                          │
                                                                          ▼
                                          VM vault /home/ubuntu/webdav/steven_vault  (Remotely Save 自动同步 Mac)
```

## 关键文件

| 位置 | 文件 | 作用 |
|------|------|------|
| Mac | `~/.agents/skills/crawl/tools/handoff_vm.py` | rsync 上传 + meta.json |
| Mac | `ingest-bilibili/bilibili.py` / `ingest-douyin/douyin.py` | 下载后 handoff |
| Mac | `config.yaml` (`vm.asr_routing`) | 路由开关 |
| VM | `/home/ubuntu/crawl-transcribe/transcribe_daemon.py` | 常驻守护 |
| VM | `transcribe_worker.py` / `publish_vault.py` / `zhipu.json` | 转录/总结/发布 |
| VM | `inbox/` `processing/` `done/` `failed/` | 工作目录 |
| vault | `04_agent/report/crawl_op_vm_YYYYMMDD.md` | 每日回执 |

## 开关

- `config.yaml` → `vm.asr_routing: true`：B站/抖音转录走 VM（常态）。
- `false`：退回本地 Groq（仍 403，仅应急，等于关闭 VM 路由）。

## 监控

```bash
# 实时看 daemon 处理日志
ssh ubuntu@175.178.210.156 'journalctl -u crawl-transcribe -f'
# 看当日回执
cat /home/ubuntu/webdav/steven_vault/04_agent/report/crawl_op_vm_$(date +%Y%m%d).md
```

## 积压回填

```bash
python3 ~/Documents/agent_spaces/ominicrawl/backfill_pending_vm.py   # 真上传
python3 ~/Documents/agent_spaces/ominicrawl/backfill_pending_vm.py --dry   # 只列清单
```

## 故障处理

- **单条失败**：VM `failed/<name>/` + `error.log`；可 `--keep` 重跑 `transcribe_worker.py <wav> <meta>` 调试。
- **daemon 挂了**：`systemctl restart crawl-transcribe`（`Restart=always` 一般已自动拉起）。
- **磁盘**：VM 仅 ~11–13G 空闲；worker 成功即删源音频，`done/` 保留 7 天自动清。
- **inbox 堆积**：daemon 串行（并发=1），约 70s/条；积压多时耐心等，勿手动删 inbox 里的 `.wav`+`.meta.json` 配对。

## 回滚

若 VM 不可用，把 `vm.asr_routing` 改 `false`，转录退回 Groq（需解决 403 才有用）。Mac 端下载逻辑不变。
