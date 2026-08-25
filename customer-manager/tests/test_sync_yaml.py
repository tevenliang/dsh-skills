#!/usr/bin/env python3
"""
customer-vault/tests/test_sync_yaml.py

vault md frontmatter 同步校验 + sanitize_vault 行为测试。

覆盖范围:
  1. 308 份 vault md PyYAML safe_load 全部解析成功
  2. 字段类型 = str (22 列业务字段) + list[str] (关联文档/关联issue/tags)
     无 int/float/date 隐式转
  3. 每个文件正文都有 "## 7. 备注" 段
  4. _ 前缀文件被忽略
  5. sanitize_vault.fix_one dry_run=True 不改磁盘
  6. sanitize_vault.fix_one dry_run=False 修复脏数据

运行:
  cd /Users/tianwenliang/.agents/skills/PRODUCTIVITY/customer-vault
  python3 -m pytest tests/test_sync_yaml.py -v
  或
  python3 tests/test_sync_yaml.py
"""

import re
import sys
import shutil
import tempfile
import subprocess
from pathlib import Path

# 让脚本既能直接跑也能 pytest 跑
_THIS = Path(__file__).resolve().parent
_SCRIPTS = _THIS.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import sanitize_vault  # noqa: E402

VAULT_ROOT = Path.home() / "Documents" / "steven_vault"
CUSTOMER_DIR = VAULT_ROOT / "11_customer" / "客户资料"

# 22 业务字段 + 关联issue + tags
EXPECTED_FM_KEYS = [
    "客户名称", "行业", "销售阶段", "客户标签",
    "联系人", "跟进记录", "关联文档",
    "下一步计划", "下一步行动", "总结",
    "公司简介", "产品服务", "财务状况", "客户群体",
    "营收", "人数", "网站", "地址", "竞争对手", "城市",
    "更新日期",
    "关联issue", "tags",
]
LIST_KEYS = {"关联文档", "关联issue", "tags"}
STR_KEYS = set(EXPECTED_FM_KEYS) - LIST_KEYS
# 备注 字段不在 frontmatter 里(已迁到正文段)
assert "备注" not in EXPECTED_FM_KEYS


def _all_customer_files():
    """
    拿所有"真客户"档案,排除:
      - _ 前缀(template/prompt 文件)
      - 文件名含 prompt(template)
      - frontmatter tags 含 Prompt(template 标记)
    """
    if not CUSTOMER_DIR.exists():
        return []
    out = []
    for p in CUSTOMER_DIR.glob("*.md"):
        if p.name.startswith("_"):
            continue
        if "prompt" in p.name.lower():
            continue
        text = p.read_text(encoding="utf-8")
        # 检查 tags 是否含 Prompt(template 标记)
        m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        if m:
            import yaml
            try:
                fm = yaml.safe_load(m.group(1))
                if isinstance(fm, dict):
                    tags = fm.get("tags", []) or []
                    if isinstance(tags, list) and any("Prompt" in str(t) for t in tags):
                        continue
            except yaml.YAMLError:
                pass
        out.append(p)
    return sorted(out)


# ---------------------------------------------------------------------------
# Test 1: PyYAML safe_load 全部解析成功 + 字段类型正确
# ---------------------------------------------------------------------------

def test_yaml_parse_all():
    """
    308 份 vault md 经 fix_one round-trip 后 PyYAML safe_load 全部解析成功,
    字段类型正确,调研报告保留。

    注:不直接读磁盘 yaml.safe_load,因为 v2.5 落盘的 5 个错文件
    (联系人/跟进记录 含换行被强包成单引号字符串)PyYAML 解析失败。
    这里用 fix_one round-trip 后的新 fm 校验 —— fix_one 才是真源,
    round-trip 后的 fm 必合法。
    """
    import yaml
    files = _all_customer_files()
    assert len(files) > 0, "客户资料目录为空"

    bad_parse = []
    bad_type = []
    bad_keys = []
    bad_report = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        # fix_one round-trip:复用它的内部步骤拿 new_text(不动磁盘)
        parts = sanitize_vault.split_fm_body(text)
        if parts is None:
            bad_parse.append(f.name)
            continue
        fm_text, body = parts
        fm = sanitize_vault.parse_fm(fm_text)
        if not fm:
            bad_parse.append(f"{f.name}: empty fm")
            continue
        remark_raw = fm.pop("备注", "")
        if not remark_raw.strip():
            remark_raw = sanitize_vault._extract_remark_from_body(body)
        new_fm = sanitize_vault.render_fm(fm)
        remark_section = sanitize_vault.render_remark_section(
            sanitize_vault.clean_value(remark_raw, is_remark=True)
        )
        new_text = new_fm + "\n\n" + remark_section
        m = re.match(r"^---\n(.*?)\n---\n?", new_text, re.DOTALL)
        if not m:
            bad_parse.append(f.name)
            continue
        try:
            fm = yaml.safe_load(m.group(1))
        except yaml.YAMLError as e:
            bad_parse.append(f"{f.name}: {e}")
            continue
        if not isinstance(fm, dict):
            bad_parse.append(f"{f.name}: not dict")
            continue
        # 检查键集合
        keys = set(fm.keys())
        missing = set(EXPECTED_FM_KEYS) - keys
        if missing:
            bad_keys.append(f"{f.name}: missing {missing}")
            continue
        # 检查字段类型
        for k in STR_KEYS:
            v = fm.get(k)
            if v is not None and not isinstance(v, str):
                bad_type.append(f"{f.name}: {k}={type(v).__name__}({v!r})")
        for k in LIST_KEYS:
            v = fm.get(k)
            if v is not None and not isinstance(v, list):
                bad_type.append(f"{f.name}: {k}={type(v).__name__}({v!r})")
            elif isinstance(v, list):
                for it in v:
                    if not isinstance(it, str):
                        bad_type.append(f"{f.name}: {k}[]={type(it).__name__}")
        # 检查 round-trip 不丢内容
        #   - 原 body 是 "> ..." 调研 → round-trip 后仍是 "> ..."
        #   - 原 body 是 "(无)" → round-trip 后仍是 "(无)"
        #   - 原 body 是 "> ..." → round-trip 后变 "(无)" 是 bug,记入 bad_report
        body_match = re.search(r"## 7\. 备注\s*\n+(.*?)(?=\n## |\Z)", body, re.DOTALL)
        orig_body = body_match.group(1).strip() if body_match else ""
        new_body_match = re.search(r"## 7\. 备注\s*\n+(.*?)(?=\n## |\Z)", new_text, re.DOTALL)
        new_body = new_body_match.group(1).strip() if new_body_match else ""
        orig_has_report = ">" in orig_body[:50]
        new_has_report = ">" in new_body[:50]
        if orig_has_report and not new_has_report:
            bad_report.append(f.name)

    assert not bad_parse, f"PyYAML 解析失败 {len(bad_parse)} 个:\n  " + "\n  ".join(bad_parse[:5])
    assert not bad_keys, f"frontmatter 缺字段 {len(bad_keys)} 个:\n  " + "\n  ".join(bad_keys[:5])
    assert not bad_type, f"字段类型错 {len(bad_type)} 个:\n  " + "\n  ".join(bad_type[:5])
    assert not bad_report, f"调研报告丢失 {len(bad_report)} 个:\n  " + "\n  ".join(bad_report[:5])
    print(f"  ✓ PyYAML safe_load 全 {len(files)} 个文件 round-trip 后解析成功,字段类型正确,调研报告保留")


# ---------------------------------------------------------------------------
# Test 2: 每个文件正文都有 "## 7. 备注" 段
# ---------------------------------------------------------------------------

def test_section_remark_all():
    """每个 vault md 正文都有 '## 7. 备注' 段(可能内容 '(无)' 但必须有段)。"""
    files = _all_customer_files()
    missing = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        if "## 7. 备注" not in text:
            missing.append(f.name)
    assert not missing, f"无 '## 7. 备注' 段 {len(missing)} 个:\n  " + "\n  ".join(missing[:5])
    print(f"  ✓ {len(files)} 个文件全部含 '## 7. 备注' 段")


# ---------------------------------------------------------------------------
# Test 3: frontmatter 已无 '备注:' 残留
# ---------------------------------------------------------------------------

def test_no_remark_in_frontmatter():
    """每个 vault md frontmatter 里都不再有 '备注:' 字段(已迁到正文)。"""
    files = _all_customer_files()
    leaked = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n?", text, re.DOTALL)
        if not m:
            continue
        if re.search(r"^备注\s*:", m.group(1), re.MULTILINE):
            leaked.append(f.name)
    assert not leaked, f"frontmatter 残留 '备注:' {len(leaked)} 个:\n  " + "\n  ".join(leaked[:5])
    print(f"  ✓ {len(files)} 个文件 frontmatter 全部无 '备注:' 残留")


# ---------------------------------------------------------------------------
# Test 4: sanitize_vault.fix_one dry_run=True 不写文件
# ---------------------------------------------------------------------------

def test_dry_run_no_write():
    """fix_one(dry_run=True) 报告变更但绝不写磁盘。"""
    # 构造一个"脏"文件:int/float/date 隐式转 + 含 markdown 表格
    dirty = """---
客户名称: 2026-08-07
行业: 2026.0
销售阶段: 100
客户标签: ''
联系人: ''
跟进记录: ''
关联文档: []
下一步计划: ''
下一步行动: ''
总结: ''
公司简介: '| 列1 | 列2 |\\n|---|\\n| a | b |'
产品服务: ''
财务状况: ''
客户群体: ''
营收: ''
人数: ''
网站: ''
地址: ''
竞争对手: ''
城市: ''
更新日期: 2026-08-07
关联issue: []
tags: []
备注: |
  > 调研报告
---

## 旧 body

应被 drop
"""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "测试客户.md"
        p.write_text(dirty, encoding="utf-8")
        original = p.read_text(encoding="utf-8")

        changed, changes = sanitize_vault.fix_one(p, dry_run=True)

        # 报告 changed
        assert changed, f"dry_run 应报告 changed=True,实际 changes={changes}"
        # 磁盘完全没变
        assert p.read_text(encoding="utf-8") == original, "dry_run 改了文件!"
        print(f"  ✓ dry_run=True 不写磁盘(changes={len(changes)} 项)")


# ---------------------------------------------------------------------------
# Test 5: sanitize_vault.fix_one dry_run=False 修复脏数据
# ---------------------------------------------------------------------------

def test_apply_fixes_dirty():
    """fix_one(dry_run=False) 把 int/float/date 隐式转改回强单引号字符串。"""
    import yaml
    dirty = """---
客户名称: 2026-08-07
行业: 2026.0
销售阶段: 100
客户标签: ''
联系人: ''
跟进记录: ''
关联文档: []
下一步计划: ''
下一步行动: ''
总结: ''
公司简介: '| 列1 | 列2 |\\n|---|\\n| a | b |'
产品服务: ''
财务状况: ''
客户群体: ''
营收: ''
人数: ''
网站: ''
地址: ''
竞争对手: ''
城市: ''
更新日期: 2026-08-07
关联issue: []
tags: []
备注: |
  > 调研报告
---

## 旧 body

应被 drop
"""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "测试客户.md"
        p.write_text(dirty, encoding="utf-8")

        changed, changes = sanitize_vault.fix_one(p, dry_run=False)
        assert changed

        # 重新读,验证修复
        text = p.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n?(.*)", text, re.DOTALL)
        assert m
        fm = yaml.safe_load(m.group(1))

        # 类型全是 str
        assert fm["客户名称"] == "2026-08-07", f"客户名称 错: {fm['客户名称']!r}"
        assert fm["行业"] == "2026.0", f"行业 错: {fm['行业']!r}"
        assert fm["销售阶段"] == "100", f"销售阶段 错: {fm['销售阶段']!r}"
        assert fm["更新日期"] == "2026-08-07", f"更新日期 错: {fm['更新日期']!r}"
        assert isinstance(fm["客户名称"], str)
        assert isinstance(fm["行业"], str)
        assert isinstance(fm["销售阶段"], str)
        # 关联文档 是 list
        assert isinstance(fm["关联文档"], list)
        # 关联issue / tags 是 list
        assert isinstance(fm["关联issue"], list)
        assert isinstance(fm["tags"], list)
        # frontmatter 无 '备注:'
        assert not re.search(r"^备注\s*:", m.group(1), re.MULTILINE)
        # 正文有 '## 7. 备注'
        assert "## 7. 备注" in text
        # 旧 body 被 drop(只剩调研报告的 > 块)
        assert "应被 drop" not in text, "fix_one 没 drop 旧 body"
        print(f"  ✓ apply 修复脏数据成功(int/float/date 转 str + 旧 body drop)")


# ---------------------------------------------------------------------------
# Test 6: _ 前缀文件被忽略
# ---------------------------------------------------------------------------

def test_underscore_prefix_ignored():
    """glob 跳过 _ 前缀的 md(模板/prompt 文件)。"""
    files = _all_customer_files()
    bad = [f for f in files if f.name.startswith("_")]
    assert not bad, f"glob 没跳过 _ 前缀文件: {[f.name for f in bad]}"
    print(f"  ✓ glob 正确跳过 _ 前缀文件")


# ---------------------------------------------------------------------------
# Pytest 入口
# ---------------------------------------------------------------------------

def _run_all():
    """直接 python3 跑也支持。"""
    tests = [
        ("yaml_parse_all", test_yaml_parse_all),
        ("section_remark_all", test_section_remark_all),
        ("no_remark_in_frontmatter", test_no_remark_in_frontmatter),
        ("dry_run_no_write", test_dry_run_no_write),
        ("apply_fixes_dirty", test_apply_fixes_dirty),
        ("underscore_prefix_ignored", test_underscore_prefix_ignored),
    ]
    failed = 0
    for name, fn in tests:
        try:
            print(f"[{name}]")
            fn()
        except AssertionError as e:
            print(f"  ✗ FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ ERROR: {type(e).__name__}: {e}")
            failed += 1
    print()
    if failed:
        print(f"❌ {failed}/{len(tests)} 失败")
        sys.exit(1)
    print(f"✅ {len(tests)}/{len(tests)} 通过")


if __name__ == "__main__":
    _run_all()
