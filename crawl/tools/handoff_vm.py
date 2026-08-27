#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handoff_vm.py — crawl 3.1.0 Mac→VM 音频交接模块

职责:
  把 Mac 本地已下载的音频 + meta.json rsync 到 VM 的 inbox/ 目录，
  由 VM 侧 transcribe_worker / daemon 异步完成 转录→总结→发布到 Obsidian。

Mac 端只做「下载」，后续「转录→总结→发布」全部交给 VM（设计文档 3.1.0）。

meta.json 格式必须严格对齐 VM 端 transcribe_worker.py 的读取契约:
  {
    "platform": "bilibili" | "douyin",
    "author":   "<作者名>",
    "title":    "<视频标题>",
    "source_url": "<原始视频链接>",
    "publish_date": "<YYYY-MM-DD 或留空>",
    "desc":     "<视频简介/描述，留空则 VM 不写 ## 描述 段>"
  }

依赖: rsync（Mac 自带 /usr/bin/rsync）+ Mac→VM 已配置 SSH 免密。

用法:
  from tools.handoff_vm import handoff_to_vm
  ok = handoff_to_vm(
      wav_path="/tmp/xxx.wav",
      platform="bilibili",
      video_id="BV1sPu56uES1",
      title="美国非农数据解读",
      author="财经观察",
      source_url="https://www.bilibili.com/video/BV1sPu56uES1",
      publish_date="2026-08-09",
  )
"""
import json
import shutil
import subprocess
from pathlib import Path

# ── 默认 VM 连接参数（优先被 config.yaml 的 vm: 段覆盖）──────────────
VM_HOST = "175.178.210.156"
VM_USER = "ubuntu"
VM_INBOX = "/home/ubuntu/crawl-transcribe/inbox"

# 上传文件名约定（对齐设计文档 §4）:
#   inbox/{platform}_{video_id}.wav
#   inbox/{platform}_{video_id}.meta.json


def _load_vm_cfg():
    """从 config.yaml 的 vm: 段读取 host/user/inbox，缺省用内置默认值。"""
    try:
        import yaml
        cfg_path = Path(__file__).resolve().parent.parent / "config.yaml"
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        vm = cfg.get("vm", {}) or {}
        return (
            vm.get("host", VM_HOST),
            vm.get("user", VM_USER),
            vm.get("crawl_transcribe_inbox", VM_INBOX),
        )
    except Exception:
        return VM_HOST, VM_USER, VM_INBOX


def vm_routing_enabled(platform=None):
    """判断某平台是否走 VM 转录路由。

    读 config.yaml 的 vm.asr_routing；仅 bilibili/douyin 受此路由影响。
    默认 False（仍走本地 Groq），等 VM daemon(D 阶段) 联调通过后再置 True。
    """
    try:
        import yaml
        cfg_path = Path(__file__).resolve().parent.parent / "config.yaml"
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        vm = cfg.get("vm", {}) or {}
        if not vm.get("asr_routing", False):
            return False
    except Exception:
        return False
    if platform is None:
        return True
    return platform in ("bilibili", "douyin")


def _remote_cmd(cmd, timeout=30):
    """在 VM 上执行命令，返回 (returncode, stdout, stderr)。"""
    host, user, _ = _load_vm_cfg()
    ssh_cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", f"ConnectTimeout={timeout}",
               f"{user}@{host}", cmd]
    try:
        r = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "ssh timeout"
    except Exception as e:
        return -1, "", str(e)


def _remote_size(path):
    """获取 VM 上文件的字节数，失败返回 -1。"""
    rc, out, err = _remote_cmd(f"stat -c %s '{path}' 2>/dev/null || echo -1")
    try:
        return int(out.strip())
    except Exception:
        return -1


def handoff_to_vm(wav_path, platform, video_id,
                  title="", author="", source_url="", publish_date="",
                  desc="", timeout=180):
    """上传单个音频 + meta.json 到 VM inbox。

    原子性保障（三阶段）：
    1. 先 rsync 到 .uploading 临时名
    2. ssh rename 到最终名字（原子操作）
    3. 验证远程文件大小匹配本地

    Args:
        wav_path:    本地音频绝对路径（wav/mp3/mp4/m4a 等）
        platform:    "bilibili" / "douyin"
        video_id:    bvid 或 aweme_id（作为文件名标识）
        title:       视频标题（给 VM 发布用）
        author:      作者名（给 VM 发布用）
        source_url:  原始视频链接
        publish_date: 发布日期 YYYY-MM-DD（给 VM 发布用，留空则 VM 用当天）
        desc:        视频简介/描述（给 VM 写 ## 描述 段，留空则 VM 不写）
        timeout:     rsync 超时秒数（防公网卡死）
    Returns:
        bool: 上传成功 True / 失败 False
    """
    wav_path = Path(wav_path)
    if not wav_path.exists() or wav_path.stat().st_size == 0:
        print(f"  ⚠️ [handoff] 音频不存在或为空: {wav_path}")
        return False
    if platform not in ("bilibili", "douyin"):
        print(f"  ⚠️ [handoff] 不支持的平台(仅 bilibili/douyin): {platform}")
        return False

    host, user, inbox = _load_vm_cfg()
    ext = wav_path.suffix or ".wav"
    base = f"{platform}_{video_id}"
    # .uploading 后缀表示传输中，VM worker 不会处理此类文件
    uploading_suffix = ".uploading"
    remote_wav_tmp = f"{base}{ext}{uploading_suffix}"
    remote_meta_tmp = f"{base}.meta.json{uploading_suffix}"

    # 构造 meta.json（临时落盘，rsync 完成后删除）
    meta = {
        "platform": platform,
        "author": author or "未知作者",
        "title": title or video_id,
        "source_url": source_url or "",
        "publish_date": publish_date or "",
        "desc": desc or "",
    }
    meta_local = wav_path.parent / f"{base}.meta.json"
    meta_local.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # wav 需重命名为 {base}{ext} 再上传，保证与 meta.json 同名（VM worker 契约：
    # inbox/<name>.wav + inbox/<name>.meta.json 必须同名）。
    wav_local_tmp = wav_path.parent / f"{base}{ext}"
    _wav_copied = False
    if wav_local_tmp != wav_path:
        try:
            shutil.copy2(wav_path, wav_local_tmp)
            _wav_copied = True
        except Exception as e:
            print(f"  ⚠️ [handoff] wav 重命名失败, 用原名上传: {e}")
            wav_local_tmp = wav_path

    target = f"{user}@{host}:{inbox}/"

    # ── 阶段 1: rsync 到 .uploading 临时名 ─────────────────────────────
    # rsync over SSH（已配免密）。-a 归档保留权限；--timeout 防 I/O 卡死。
    # 先传 meta.json，再传 wav（wav 通常更大）
    for local_file, remote_file in [(str(meta_local), remote_meta_tmp),
                                   (str(wav_local_tmp), remote_wav_tmp)]:
        cmd = [
            "rsync", "-a", "--timeout", str(timeout),
            local_file, f"{target}{remote_file}",
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=timeout + 30)
            if r.returncode != 0:
                err = (r.stderr or r.stdout).strip()
                print(f"  ⚠️ [handoff] rsync 失败 (rc={r.returncode}): {err[:200]}")
                _cleanup_local(meta_local, wav_local_tmp, _wav_copied)
                return False
        except subprocess.TimeoutExpired:
            print(f"  ⚠️ [handoff] rsync 超时 ({timeout}s)")
            _cleanup_local(meta_local, wav_local_tmp, _wav_copied)
            return False
        except Exception as e:
            print(f"  ⚠️ [handoff] 异常: {e}")
            _cleanup_local(meta_local, wav_local_tmp, _wav_copied)
            return False

    # ── 阶段 2: ssh rename 到最终名字（原子操作）─────────────────────
    # mv 命令在 POSIX 系统上是原子的（同一文件系统）
    wav_final = f"{base}{ext}"
    meta_final = f"{base}.meta.json"
    rc_rename, out_rename, err_rename = _remote_cmd(
        f"mv '{inbox}/{remote_wav_tmp}' '{inbox}/{wav_final}' && "
        f"mv '{inbox}/{remote_meta_tmp}' '{inbox}/{meta_final}'"
    )
    if rc_rename != 0:
        print(f"  ⚠️ [handoff] VM rename 失败: {err_rename[:200]}")
        # 尝试清理远程 .uploading 文件
        _remote_cmd(f"rm -f '{inbox}/{remote_wav_tmp}' '{inbox}/{remote_meta_tmp}'")
        _cleanup_local(meta_local, wav_local_tmp, _wav_copied)
        return False

    # ── 阶段 3: 验证远程文件大小匹配本地 ─────────────────────────────
    local_wav_size = wav_path.stat().st_size
    local_meta_size = meta_local.stat().st_size
    remote_wav_size = _remote_size(f"{inbox}/{wav_final}")
    remote_meta_size = _remote_size(f"{inbox}/{meta_final}")

    if remote_wav_size != local_wav_size:
        print(f"  ⚠️ [handoff] wav 大小不匹配: 本地={local_wav_size} 远程={remote_wav_size}")
        _cleanup_local(meta_local, wav_local_tmp, _wav_copied)
        return False
    if remote_meta_size != local_meta_size:
        print(f"  ⚠️ [handoff] meta.json 大小不匹配: 本地={local_meta_size} 远程={remote_meta_size}")
        _cleanup_local(meta_local, wav_local_tmp, _wav_copied)
        return False

    # 全部成功，清理本地临时文件
    _cleanup_local(meta_local, wav_local_tmp, _wav_copied)
    print(f"  ✅ [handoff] 已上传 VM inbox → {base}{ext} + {base}.meta.json (验证通过)")
    return True


def _cleanup_local(meta_local, wav_local_tmp, wav_copied):
    """清理本地临时文件。"""
    try:
        meta_local.unlink()
    except Exception:
        pass
    if wav_copied:
        try:
            wav_local_tmp.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print("用法: python handoff_vm.py <wav_path> <platform> <video_id> [title] [author] [source_url] [publish_date]")
        sys.exit(1)
    ok = handoff_to_vm(
        sys.argv[1], sys.argv[2], sys.argv[3],
        title=sys.argv[4] if len(sys.argv) > 4 else "",
        author=sys.argv[5] if len(sys.argv) > 5 else "",
        source_url=sys.argv[6] if len(sys.argv) > 6 else "",
        publish_date=sys.argv[7] if len(sys.argv) > 7 else "",
    )
    sys.exit(0 if ok else 1)
