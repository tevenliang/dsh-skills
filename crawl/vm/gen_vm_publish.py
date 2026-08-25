#!/usr/bin/env python3
"""从 common-publish/publish_vault.py 重建 crawl/vm/publish_vault.py。

原则: common-publish 是 Mac 端 + 唯一真相源(含全部 2026-08-15 修复)。
vm 版 = 真相源 + VM 专属适配(4 处), 并保留 vm 独有的 3.1.0 覆盖逻辑。

确定性文本变换, 便于 review 与复现。
"""
import io, sys

SRC = "/Users/tianwenliang/.agents/skills/crawl/common-publish/publish_vault.py"
DST = "/Users/tianwenliang/.agents/skills/crawl/vm/publish_vault.py"

with open(SRC, encoding="utf-8") as f:
    s = f.read()

# 1) 去掉 Mac 专属 sys.path 注入 (VM 直接 import publish_vault)
old_sys = (
    'if "/Users/tianwenliang/.agents/skills/crawl/common-publish" not in _sys.path:\n'
    '    _sys.path.insert(0, "/Users/tianwenliang/.agents/skills/crawl/common-publish")'
)
new_sys = '# (common-publish path removed for VM: transcribe_worker/ocr_daemon import publish_vault directly)'
assert old_sys in s, "sys.path 锚点未命中"
s = s.replace(old_sys, new_sys, 1)

# 2) VAULT 默认路径 -> VM WebDAV vault
old_vault = 'VAULT = Path(os.environ.get("VAULT", "/Users/tianwenliang/Documents/steven_vault"))'
new_vault = 'VAULT = Path(os.environ.get("VAULT", "/home/ubuntu/webdav/steven_vault"))'
assert old_vault in s, "VAULT 锚点未命中"
s = s.replace(old_vault, new_vault, 1)

# 3) STATE_DIR -> VM 绝对路径 (Path.home() 在 VM 也是 /home/ubuntu, 但显式更稳)
old_state = 'STATE_DIR = Path.home() / ".agents" / "skills" / "crawl" / "state"'
new_state = 'STATE_DIR = Path("/home/ubuntu") / ".agents" / "skills" / "crawl" / "state"'
assert old_state in s, "STATE_DIR 锚点未命中"
s = s.replace(old_state, new_state, 1)

# 4) 保留 vm 独有 3.1.0 覆盖逻辑: 把 common-publish 的"序号化防重名"换成直接覆盖
old_renum = (
    '    # 防重名：同名文件加序号\n'
    '    fpath = author_dir / fname\n'
    '    if fpath.exists():\n'
    '        n = 1\n'
    '        while fpath.exists():\n'
    '            fpath = author_dir / f"{date_str}_{safe_title}_{n}.md"\n'
    '            n += 1\n'
)
new_renum = (
    '    # crawl 3.1.0 fix: 已存在则直接覆盖（worker 是 handoff 条目的权威发布方，\n'
    '    # 旧版序号化成 _1.md 会与 16:19 抓出的空壳并存，造成重复且段名混乱）。\n'
    '    fpath = author_dir / fname\n'
)
assert old_renum in s, "防重名序号化 锚点未命中"
s = s.replace(old_renum, new_renum, 1)

# 语法校验
import ast
ast.parse(s)
print("✅ 语法 OK")

with open(DST, "w", encoding="utf-8") as f:
    f.write(s)
print(f"✅ 写入 {DST} ({len(s)} chars)")
