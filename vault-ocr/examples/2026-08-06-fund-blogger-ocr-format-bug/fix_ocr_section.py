#!/usr/bin/env python3
"""
fix_ocr_section.py — 修复 vault-ocr 输出的 Markdown 渲染问题

用法:
    python3 fix_ocr_section.py <vault-path>/article.md

适用场景 (2026-08-07 案例):
    百炼 qwen3-vl-plus 对图片 OCR 时偶尔:
      - 漏写标题行前的 '#'
      - 把整张表格误识别为 markdown 代码块 (```markdown ... ```)

    这两个问题会导致 Obsidian 中表格渲染异常。
    本脚本在不动 OCR 文本内容的前提下, 修正 Markdown 渲染结构。

设计原则:
    - 不重新调用 bl vision describe (避免重复计费 + 同样问题可能再出现)
    - 启发式判断, 不假设每张图都有标题行
    - 处理后输出变更摘要, 便于审计
"""
import re
import sys
from pathlib import Path


def fix_section(text: str, fixes_log: list) -> str:
    """对单篇 vault 文章的 OCR 区块做格式修复"""

    # 修复 1: 去除 ```markdown ... ``` 误包裹
    # 模式 1: ### 图片 N\n\n```markdown\n  →  ### 图片 N\n\n
    pattern1 = re.compile(r'(### 图[^\n]+\n\n)```markdown\n')
    new_text, n1 = pattern1.subn(r'\1', text)
    if n1 > 0:
        fixes_log.append(f"✓ 移除 {n1} 处 ```markdown 误包裹")
        text = new_text

    # 模式 2: ```\n### 图  →  ### 图 (去掉包裹的尾 ```)
    pattern2 = re.compile(r'```\n(### 图)')
    new_text, n2 = pattern2.subn(r'\1', text)
    if n2 > 0:
        fixes_log.append(f"✓ 移除 {n2} 处尾 ```")
        text = new_text

    # 修复 2: 标题缺 '#'  (启发式: ### 图片 N 之后空行+短行+非 # 开头)
    section_pattern = re.compile(
        r'(### 图片 \d+\n\n)([^\n#|].{0,30})(\n)',
        flags=re.UNICODE
    )

    def is_likely_title(line: str) -> bool:
        """启发式: 中文 / 数字 + 长度 ≤ 30 + 不以 | 开头 + 不是已 # 标题"""
        if line.startswith('#') or line.startswith('|'):
            return False
        if len(line) < 4 or len(line) > 30:
            return False
        has_chinese = any('\u4e00' <= c <= '\u9fff' for c in line)
        has_digit = any(c.isdigit() for c in line)
        return has_chinese or has_digit

    new_text = section_pattern.sub(
        lambda m: m.group(1) + ('# ' + m.group(2) if is_likely_title(m.group(2)) else m.group(2)) + m.group(3),
        text
    )
    if new_text != text:
        # 计算实际补全数量 (对比前后差)
        before_lines = [l for l in text.split('\n') if l.startswith('# ')]
        after_lines = [l for l in new_text.split('\n') if l.startswith('# ')]
        added = len(after_lines) - len(before_lines)
        fixes_log.append(f"✓ 补全 {added} 处标题行 '#' 前缀")
        text = new_text

    return text


def main():
    if len(sys.argv) != 2:
        print("用法: python3 fix_ocr_section.py <vault-path>/article.md", file=sys.stderr)
        sys.exit(1)

    p = Path(sys.argv[1])
    if not p.exists():
        print(f"文件不存在: {p}", file=sys.stderr)
        sys.exit(1)

    text = p.read_text(encoding='utf-8')
    original = text

    fixes_log = []
    fixed = fix_section(text, fixes_log)

    if not fixes_log:
        print("无需修改 (OCR 区块格式已正确)")
        return

    if fixed != original:
        p.write_text(fixed, encoding='utf-8')
        print('\n'.join(fixes_log))
        print(f"\n✅ 已写入 {p} ({len(original)} → {len(fixed)} 字符)")
    else:
        print("⚠ 检测到问题但未产生修改 (可能是 false positive, 请人工检查)")


if __name__ == '__main__':
    main()
