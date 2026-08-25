"""按 MD5 哈希对指定目录去重，相同哈希只保留一份。

策略：每组保留「文件名最短的」（优先选择去掉 `(1)`/`(2)` 后的版本）；
同长度时保留字典序最小的。

用法：
  python dedupe.py <dir>
"""
from __future__ import annotations

import hashlib
import sys
from collections import defaultdict
from pathlib import Path


def md5_of(p: Path) -> str:
    h = hashlib.md5()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def dedupe_dir(raw: Path) -> tuple[int, int, list[tuple[Path, str]]]:
    files = [p for p in raw.iterdir() if p.is_file()]
    by_hash: dict[str, list[Path]] = defaultdict(list)
    for p in files:
        by_hash[md5_of(p)].append(p)

    kept: list[Path] = []
    removed: list[tuple[Path, str]] = []
    for digest, group in by_hash.items():
        group_sorted = sorted(group, key=lambda x: (len(x.name), x.name))
        keeper = group_sorted[0]
        kept.append(keeper)
        for dup in group_sorted[1:]:
            removed.append((dup, keeper.name))

    for dup, _ in removed:
        dup.unlink()

    return len(files), len(kept), removed


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python dedupe.py <dir>")
        return 1
    raw = Path(sys.argv[1]).expanduser().resolve()
    if not raw.is_dir():
        print(f"目录不存在: {raw}")
        return 1

    total, kept, removed = dedupe_dir(raw)
    print(f"[{raw.name}] 原始 {total} → 去重 {kept}（删除 {len(removed)}）")
    for dup, keeper in removed:
        print(f"  - {dup.name}  (与 {keeper} 重复)")
    return 0


if __name__ == "__main__":
    sys.exit(main())