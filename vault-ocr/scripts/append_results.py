#!/usr/bin/env python3
"""Append or replace a Bailian vision OCR section in a Vault Markdown note."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

MARKER = "## 图片识别结果（百炼 OCR）"


def extract_content(path: Path) -> str:
    raw = path.read_text(encoding="utf-8").strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw

    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"无法从 {path} 读取 choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise ValueError(f"{path} 的 OCR content 为空")
    return content.strip()


def build_section(result_files: list[Path], model: str) -> str:
    blocks = [
        MARKER,
        "",
        f"> 识别模型：阿里云百炼 `{model}`。以下内容按图片顺序转写；仅为公开信息整理，不构成投资建议。",
        "",
    ]
    for index, result_file in enumerate(result_files, 1):
        blocks.extend([f"### 图片 {index}", "", extract_content(result_file), ""])
    return "\n".join(blocks).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("article", type=Path, help="源 Markdown 文件")
    parser.add_argument("results", type=Path, nargs="+", help="bl vision describe 的 JSON 或纯文本结果文件")
    parser.add_argument("--model", default="qwen3-vl-plus", help="识别模型名")
    parser.add_argument("--replace-existing", action="store_true", help="已有 OCR 区块时替换到文件末尾")
    args = parser.parse_args()

    if not args.article.is_file():
        raise SystemExit(f"源文件不存在：{args.article}")
    missing = [str(path) for path in args.results if not path.is_file()]
    if missing:
        raise SystemExit("结果文件不存在：" + ", ".join(missing))

    original = args.article.read_text(encoding="utf-8")
    section = build_section(args.results, args.model)
    if MARKER in original:
        if not args.replace_existing:
            raise SystemExit("源文件已存在 OCR 区块；如需重做，请加 --replace-existing")
        original = original.split(MARKER, 1)[0].rstrip() + "\n\n"
    else:
        original = original.rstrip() + "\n\n"

    args.article.write_text(original + section, encoding="utf-8")
    print(f"已写入 {args.article}：{len(args.results)} 个 OCR 结果")


if __name__ == "__main__":
    main()
