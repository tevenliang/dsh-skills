#!/usr/bin/env python3
"""
pull_vm_vault.py — 从 VM vault 拉取 OCR 结果到 Mac vault

Mac vault ← VM vault (rsync pull，支持定时 cron 调用)

用法:
  python pull_vm_vault.py xhs          # 只拉取 xhs
  python pull_vm_vault.py bilibili     # 只拉取 bilibili
  python pull_vm_vault.py douyin       # 只拉取 douyin
  python pull_vm_vault.py              # 默认拉取 xhs
  python pull_vm_vault.py --check      # receipt-based 增量拉取（有新 receipt 才拉）
"""
import subprocess, sys, os
from pathlib import Path

VM = "ubuntu@175.178.210.156"
VM_VAULT = "/home/ubuntu/webdav/steven_vault"
MAC_VAULT = Path.home() / "Documents" / "steven_vault"

PLATFORM_MAP = {
    "xhs":            "subscription/xiaohongshu",
    "xiaohongshu":    "subscription/xiaohongshu",
    "bilibili":       "subscription/bilibili",
    "douyin":         "subscription/douyin",
    "all":            "subscription",
}

def pull_platform(plat_key: str) -> bool:
    rel_path = PLATFORM_MAP.get(plat_key, plat_key)
    vm_src = f"{VM}:{VM_VAULT}/{rel_path}/"
    mac_dst = MAC_VAULT / rel_path

    mac_dst.mkdir(parents=True, exist_ok=True)
    cmd = ["rsync", "-av", "--delete", vm_src, str(mac_dst) + "/"]

    try:
        r = subprocess.run(cmd, capture_output=True, timeout=180)
        if r.returncode != 0:
            stderr = r.stderr.decode("utf-8", errors="replace") if r.stderr else ""
            print(f"[pull] rsync 失败 rc={r.returncode}: {stderr.strip()[:200]}")
            return False
        stdout = r.stdout.decode("utf-8", errors="replace")
        for line in stdout.strip().split("\n"):
            if "sent" in line or "total size" in line:
                print(f"[pull] {line.strip()}")
        print(f"[pull] OK {plat_key}")
        return True
    except subprocess.TimeoutExpired:
        print(f"[pull] rsync 超时")
        return False
    except Exception as e:
        print(f"[pull] 异常: {e}")
        return False


def pull_if_receipt() -> bool:
    """检查 VM daemon receipt，有新 receipt 则 pull 对应平台"""
    STATE_DIR = Path.home() / ".agents" / "skills" / "crawl" / "state"
    receipt_marker = STATE_DIR / "ocr_receipt_seen"
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    last_receipt = receipt_marker.read_text().strip() if receipt_marker.exists() else ""

    try:
        r = subprocess.run(
            ["ssh", VM, "cat", "/home/ubuntu/crawl-transcribe/.last_ocr_note"],
            capture_output=True, timeout=15
        )
        if r.returncode != 0:
            return False

        current_raw = r.stdout
        if isinstance(current_raw, bytes):
            current_raw = current_raw.decode("utf-8", errors="replace")
        current_raw = current_raw.strip()

        if not current_raw:
            return False

        if current_raw == last_receipt:
            return False  # 无新 receipt

        # 解析 platform
        if ":" in current_raw:
            plat = current_raw.split(":")[0]
        else:
            plat = "xiaohongshu"  # 默认

        print(f"[pull] New OCR receipt: {current_raw} → pulling {plat}")
        ok = pull_platform(plat)
        if ok:
            receipt_marker.write_text(current_raw)
        return ok
    except Exception as e:
        print(f"[pull] receipt check 失败: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--check":
        pull_if_receipt()
    else:
        plats = sys.argv[1:] if len(sys.argv) > 1 else ["xiaohongshu"]
        for p in plats:
            ok = pull_platform(p)
            if not ok:
                sys.exit(1)
