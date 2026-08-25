#!/usr/bin/env python3
"""
去重工具 - 上传前剔除重复文件

判定口径（已与用户确认）：
  第一级：清洗后文件名 + size 完全相同 → 视为重复候选
  第二级：候选组内计算 md5 确认，避免同 size 不同内容被误杀
  md5 只对候选组算，不做全员计算，省时。

返回：
  keep    —— 保留的文件（每组第一个）
  skipped —— 被跳过的文件，含 reason 和与哪份重复
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List


@dataclass
class FileItem:
    """待上传文件的归一化表示"""
    path: Path
    name: str            # 原始文件名
    clean_name: str      # 清洗后的文件名（用于去重比对）
    size: int


@dataclass
class DedupeResult:
    keep: List[FileItem] = field(default_factory=list)
    skipped: List[Dict] = field(default_factory=list)  # {file, reason, duplicate_of}


def _normalize_name(name: str) -> str:
    """归一化文件名用于去重比对。

    比 clean_title 更激进：还要去掉空格、大小写归一、去版本号后缀，
    因为 'workbuddy.pdf' / 'WorkBuddy.pdf' / 'WorkBuddy (1).pdf' 应视为同一份。
    """
    if not name:
        return name
    # 去掉扩展名
    stem = Path(name).stem
    # 去重复下载标记
    stem = re.sub(r"\s*[(（]\d+[)）]\s*", "", stem)
    # 去副本
    stem = re.sub(r"[-_\s]*副本$", "", stem)
    # 去空格、统一小写
    stem = re.sub(r"\s+", "", stem).lower()
    return stem


def _md5(path: Path) -> str:
    """计算文件 md5（大文件分块读）"""
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(8 * 1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def dedupe(file_paths: List[str]) -> DedupeResult:
    """对一组文件路径去重，返回 keep + skipped。

    Args:
        file_paths: 文件路径列表

    Returns:
        DedupeResult
    """
    items: List[FileItem] = []
    for fp in file_paths:
        p = Path(fp)
        if not p.exists() or not p.is_file():
            continue
        items.append(FileItem(
            path=p,
            name=p.name,
            clean_name=_normalize_name(p.name),
            size=p.stat().st_size,
        ))

    result = DedupeResult()

    # 第一级：按 (clean_name, size) 分组
    groups: Dict[tuple, List[FileItem]] = {}
    for item in items:
        key = (item.clean_name, item.size)
        groups.setdefault(key, []).append(item)

    for key, group in groups.items():
        if len(group) == 1:
            # 唯一，直接保留
            result.keep.append(group[0])
            continue

        # 第二级：size 相同的多份，算 md5 确认是否真重复
        md5_groups: Dict[str, List[FileItem]] = {}
        for item in group:
            md5_groups.setdefault(_md5(item.path), []).append(item)

        for md5_key, md5_group in md5_groups.items():
            if len(md5_group) == 1:
                # 同 size 但内容不同，保留
                result.keep.append(md5_group[0])
            else:
                # 真重复：保留第一个，其余跳过
                keeper = md5_group[0]
                result.keep.append(keeper)
                for dup in md5_group[1:]:
                    result.skipped.append({
                        "file": str(dup.path),
                        "reason": f"与 {keeper.path.name} 内容相同 (md5: {md5_key[:8]})",
                        "duplicate_of": str(keeper.path),
                    })

    return result


def format_dedupe_report(result: DedupeResult) -> str:
    """生成 Markdown 格式的去重报告"""
    lines = ["", "去重结果", ""]
    lines.append(f"保留 {len(result.keep)} | 跳过 {len(result.skipped)}")
    if result.skipped:
        lines.append("")
        lines.append("**跳过的重复文件：**")
        for s in result.skipped:
            lines.append(f"- `{Path(s['file']).name}` — {s['reason']}")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python3 dedupe.py <file1> [file2 ...]")
        sys.exit(1)
    res = dedupe(sys.argv[1:])
    print(format_dedupe_report(res))
    print("保留文件：")
    for item in res.keep:
        print(f"  {item.path}")
