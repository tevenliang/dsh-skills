#!/usr/bin/env python3
"""
fetch_log.py - subscription 抓取信号写入工具 (v5)
职责: 抓取方 (Mac) 写 .fetch.log, daemon (VM) 读它。
USE_VM=true 时同时 SSH 写 VM 本地 fetch.log，rsync 博主目录到 VM vault。
USE_VM=false 时仅写 Mac 本地 fetch.log，转录由 Mac 本地完成。
"""

import sys as _sys
from pathlib import Path as _P
_SKILL_ROOT = str(_P(__file__).resolve().parent.parent)
if _SKILL_ROOT not in _sys.path:
    _sys.path.insert(0, _SKILL_ROOT)

import os, json, sys, re
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from common.paths import notes_dir, fetch_log as _paths_fetch_log, media_dir as _paths_media_dir

TZ = timezone(timedelta(hours=8))

def _load_use_vm():
    """读取 config.yaml 的 USE_VM 开关"""
    try:
        import yaml
        config_path = Path(__file__).parent.parent / "config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                cfg = yaml.safe_load(f) or {}
                return cfg.get("USE_VM", False)
    except Exception:
        pass
    return False

USE_VM = _load_use_vm()


def _detect_share() -> Path:
    """share 目录自动检测 (mac ~/Documents/steven_share / VM /home/ubuntu/webdav/steven_share)"""
    env = os.environ.get("STEVEN_SHARE")
    if env and os.path.isdir(env):
        return Path(env)
    candidates = [
        Path("/Volumes/175.178.210.156-1/steven_share"),
        Path("/Volumes/175.178.210.156/steven_share"),
        Path.home() / "Documents" / "steven_share",
        Path("/home/ubuntu/webdav/steven_share"),
        Path("/mnt/webdav/steven_share"),
    ]
    for c in candidates:
        if c.is_dir():
            return c
    if sys.platform == "darwin":
        fb = Path.home() / "Documents" / "steven_share"
    else:
        fb = Path.home() / "steven_share"
    fb.mkdir(parents=True, exist_ok=True)
    return fb


SHARE = _detect_share()
# USE_VM=false (当前默认): .fetch.log 统一写 project_crawl/logs/.fetch.log
# USE_VM=true : 写 VM share 目录(兼容旧设计)
if USE_VM:
    FETCH_LOG = SHARE / "subscription" / ".fetch.log"
else:
    FETCH_LOG = _paths_fetch_log()
FETCH_LOG.parent.mkdir(parents=True, exist_ok=True)


def append_fetch_log(platform: str, uid: str, md_abs_path: str,
                     blogger: str = "", title: str = "",
                     transcribed_by_mac: bool = True,
                     media_abs_path: str = "",
                     extra: dict = None) -> None:
    """
    写 fetch.log + SSH VM fetch.log + rsync 博主目录到 VM。
    """
    if md_abs_path:
        md_abs = Path(md_abs_path).resolve()
        parts = md_abs.parts
        try:
            idx = parts.index("notes")  # data_root/notes/<platform>/<blogger>/...
            vault_root = Path(*parts[:idx + 1])
        except ValueError:
            vault_root = md_abs.parent
        md_relpath = str(md_abs.relative_to(vault_root)) if md_abs.is_relative_to(vault_root) else str(md_abs)
    else:
        md_abs = None
        md_relpath = ""

    media_relpath = ""
    if media_abs_path:
        ma = Path(media_abs_path).resolve()
        try:
            media_relpath = str(ma.relative_to(_paths_media_dir()))
        except ValueError:
            media_relpath = str(ma)

    entry = {
        "ts": datetime.now(TZ).isoformat(timespec="seconds"),
        "platform": platform,
        "uid": uid,
        "md_relpath": md_relpath,
        "md_abspath": str(md_abs) if md_abs else "",
        "blogger": blogger,
        "title": title,
        "transcribed_by_mac": transcribed_by_mac,
        "media_relpath": media_relpath,
    }
    if extra:
        entry.update(extra)
    line = json.dumps(entry, ensure_ascii=False)

    # 1. 始终写 Mac 本地 logs/.fetch.log (稳定可追溯, 不依赖 USE_VM) -- 2026-08-19 hotfix
    _local_log = _paths_fetch_log()
    try:
        _local_log.parent.mkdir(parents=True, exist_ok=True)
        with open(_local_log, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(f"  [fetch-log] appended: {platform}/{uid} -> {md_relpath}", flush=True)

    # USE_VM=false → 跳过 VM 操作 (本地已写入)
    if not USE_VM:
        return

    # 2. SSH 写 VM 本地 fetch.log
    try:
        import subprocess
        vm_log = "/home/ubuntu/webdav/steven_share/subscription/.fetch.log"
        escaped_line = line.replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')
        cmd = f'ssh vm "cat >> {vm_log} << ENDOFMARKER\n{escaped_line}\nENDOFMARKER"'
        subprocess.run(cmd, shell=True, capture_output=True, timeout=15)
    except Exception:
        pass

    # 3. rsync 博主目录到 VM vault
    if md_abs:
      try:
        import subprocess as _sub, os as _os
        p = md_abs.parts
        try:
            i = p.index("subscription")
            blogger_dir_local = str(Path(*p[:i+3]))
            blogger_rel = str(Path(*p[i+1:i+3]))
            if _os.path.isdir(blogger_dir_local):
                vm_target = f"/home/ubuntu/webdav/steven_vault/subscription/{blogger_rel}"
                _sub.run(
                    ["rsync", "-a", "--ignore-existing",
                     f"{blogger_dir_local}/", f"vm:{vm_target}/"],
                    capture_output=True, timeout=60
                )
        except (ValueError, IndexError, OSError):
            pass
      except Exception:
        pass


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: fetch_log.py <platform> <uid> <md_path> [blogger] [title]", file=sys.stderr)
        sys.exit(1)
    append_fetch_log(sys.argv[1], sys.argv[2], sys.argv[3],
                     sys.argv[4] if len(sys.argv) > 4 else "",
                     sys.argv[5] if len(sys.argv) > 5 else "")
    print(f"FETCH_LOG = {FETCH_LOG}")
