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

"""
common/registry.py — 工具层注册表 (ominicrawl v1)

读取 config.yaml 的 tools: 区块, 提供:
  - get_tool(platform)       → 该平台当前启用的工具名 / 或 None(禁用)
  - is_enabled(platform)
  - can_monitor(platform)     → watchlist 是否监控该平台(否则仅单链接剪藏)
  - set_tool(platform, tool)  → 写回 config.yaml (crawl set-tool 用)
  - show_tools()              → 打印当前映射

平台 → 工具 路由由配置驱动, 不在代码里硬编码, 满足用户"设置里可切换工具"。
"""
import os
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
CFG_PATH = SKILL_DIR / "config.yaml"


def _load():
    try:
        import yaml
        if CFG_PATH.exists():
            return yaml.safe_load(CFG_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {}


def _tools():
    return _load().get("tools", {}) or {}


def get_tool(platform):
    t = _tools().get(platform)
    if not t:
        return None
    if not t.get("enabled", False):
        return None
    return t.get("tool")


def is_enabled(platform):
    t = _tools().get(platform)
    return bool(t and t.get("enabled", False))


def can_monitor(platform):
    """watchlist 是否监控该平台(否则仅单链接剪藏)。"""
    t = _tools().get(platform)
    return bool(t and t.get("enabled", False) and t.get("monitor", False))


def set_tool(platform, tool):
    """把 platform 的工具改为 tool 并写回 config.yaml。"""
    import yaml
    text = CFG_PATH.read_text(encoding="utf-8")
    cfg = yaml.safe_load(text) or {}
    cfg.setdefault("tools", {})[platform] = {
        "tool": tool, "enabled": True,
        "monitor": True, "transcribe": False,
    }
    CFG_PATH.write_text(_dump(cfg), encoding="utf-8")


def _dump(cfg):
    """极简 yaml dump, 保留顺序与注释友好。"""
    try:
        import yaml
        return yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False)
    except Exception:
        return str(cfg)


def show_tools():
    lines = ["平台 → 工具 (config.yaml tools:):"]
    for plat, t in _tools().items():
        lines.append(
            f"  {plat:12s} {t.get('tool','?'):18s} "
            f"enabled={t.get('enabled')} monitor={t.get('monitor')}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "set-tool":
        set_tool(sys.argv[2], sys.argv[3])
        print(f"✅ {sys.argv[2]} → {sys.argv[3]}")
    else:
        print(show_tools())
