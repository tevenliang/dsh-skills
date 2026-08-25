import sys, os
_here = os.path.dirname(os.path.abspath(__file__))
while _here and not os.path.exists(os.path.join(_here, "_bootstrap.py")):
    _p = os.path.dirname(_here)
    if _p == _here:
        _here = None
        break
    _here = _p
if _here:
    sys.path.insert(0, _here)
import _bootstrap

"""xiaohongshu/ocr.py — 小红书笔记 OCR + 飞书写入 (从 crawl.py 抽出, 2026-07-08)

将内联在 crawl.py 中的 OCR 流程(调 xhs_ocr_rapid.sh)与飞书写入(调 common/feishu.py)
抽离为独立模块, 提升主程序可读性。log 回调由调用方传入, 避免循环依赖。
"""
import os
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent


def run_ocr(md_path: Path, log) -> None:
    """调 xhs_ocr_rapid.sh 做 OCR, 完成后写飞书. OCR 模式由 XHS_OCR_MODE 控制(默认 local)"""
    script = SKILL_DIR / "scripts" / "xhs_ocr_rapid.sh"
    if not script.exists():
        log(f"  [ocr] 脚本不存在: {script}")
        return
    env = dict(os.environ)
    env.setdefault("XHS_OCR_MODE", "local")
    try:
        result = subprocess.run(
            ["bash", str(script), str(md_path)],
            capture_output=True, text=True, timeout=120, env=env,
        )
        for line in result.stdout.splitlines():
            if "完成" in line or "✅" in line or "❌" in line:
                log(f"  [ocr] {line.strip()}")
        if result.returncode != 0:
            log(f"  [ocr] 脚本返回非0: {result.stderr.strip()[:200]}")
    except Exception as e:
        log(f"  [ocr] 失败: {e}")
    write_feishu(md_path, log)


def write_feishu(md_path: Path, log) -> None:
    """2026-07-19 脱飞书: 原调 common/feishu.py 把 OCR 结果写入飞书多维表格,
    现改为 no-op. OCR 结果已随 note 落 $VAULT/subscription (finalize → publish_vault),
    无需再推飞书. common/feishu.py 已删除."""
    ocr_path = md_path.parent / (md_path.stem + "_ocr.md")
    if ocr_path.exists():
        log(f"  [ocr] OCR 结果已写入 {ocr_path.name} (落 vault, 不再推飞书)")
    return
