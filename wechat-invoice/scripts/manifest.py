"""manifest.json 管理：记录每个微信源发票的处理状态和解析结果。

manifest 结构：
{
  "source_base": "<微信缓存根目录>",
  "companies": [...],
  "processed": {
    "<md5>": {
      "filename": "dzfp_xxx.pdf",
      "month": "2026-07",
      "status": "ok|skipped|error",
      "invoice": { ... }   // status=ok 时有
    }
  }
}
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from parse_invoices import parse_invoice


def md5_of(p: Path) -> str:
    h = hashlib.md5()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class Manifest:
    def __init__(self, path: Path):
        self.path = path
        self._data: dict = {}
        if path.exists():
            self._data = json.loads(path.read_text(encoding="utf-8"))
        self._data.setdefault("processed", {})

    @property
    def source_base(self) -> str | None:
        return self._data.get("source_base")

    @property
    def companies(self) -> list[dict]:
        return self._data.get("companies", [])

    def set_meta(self, source_base: str, companies: list[dict]) -> None:
        self._data["source_base"] = source_base
        self._data["companies"] = companies

    def get(self, digest: str) -> dict | None:
        return self._data["processed"].get(digest)

    def upsert(self, digest: str, entry: dict) -> None:
        self._data["processed"][digest] = entry

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def resolve_source_files(
    source_base: Path, months: list[str],
) -> dict[str, tuple[Path, str]]:
    """扫描源目录，返回 {md5: (Path, month)}。不含 .DS_Store。"""
    result: dict[str, tuple[Path, str]] = {}
    for m in months:
        src_dir = source_base / m
        if not src_dir.is_dir():
            continue
        for p in src_dir.iterdir():
            if not (p.is_file() and p.suffix.lower() == ".pdf" and p.name.startswith("dzfp_")):
                continue
            digest = md5_of(p)
            if digest not in result:
                result[digest] = (p, m)
    return result


def resolve_incremental(
    source_files: dict[str, tuple[Path, str]],
    manifest: Manifest,
    force_reparse: bool,
) -> tuple[list[tuple[str, Path, str]], list[tuple[str, Path, str]], list[tuple[str, Path, str]]]:
    """把源文件分为：待新增 / 待重解析 / 已缓存。

    Returns:
        new: [(digest, Path, month)] — 未处理过
        changed: [(digest, Path, month)] — 文件变了
        cached: [(digest, manifest_entry)] — 可直接复用
    """
    new, changed, cached = [], [], []
    for digest, (path, month) in source_files.items():
        existing = manifest.get(digest)
        if existing is None:
            new.append((digest, path, month))
        elif existing.get("filename") != path.name:
            changed.append((digest, path, month))
        elif force_reparse:
            changed.append((digest, path, month))
        else:
            cached.append((digest, existing))
    return new, changed, cached


def build_invoice_number_index(manifest: Manifest) -> dict[str, list[str]]:
    """建立 {发票号码: [md5列表]} 索引，用于发票号级去重。"""
    idx: dict[str, list[str]] = {}
    for digest, entry in manifest._data.get("processed", {}).items():
        if entry.get("status") == "ok" and entry.get("invoice", {}).get("发票号码"):
            inv_num = entry["invoice"]["发票号码"]
            idx.setdefault(inv_num, []).append(digest)
    return idx


