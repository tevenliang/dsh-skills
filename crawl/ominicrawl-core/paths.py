#!/usr/bin/env python3
"""
paths.py - subscription-crawl 本地资产目录集中管理 (v9.2)

设计目标:
  1. 完全脱离 steven_vault(用户将删除该目录) — 旧 vault/media 仅作只读兜底。
  2. 所有本地资产统一收敛到单一项目目录 project_root, 不再分散在
     ~/Library/Caches、~/.codex、VM webdav 等各处。
  3. 凭证(飞书 / 智谱)也随项目走, 优先读 project_root/credentials,
     系统级 ~/.agents/credentials/ominicrawl 作兜底。

project_root 默认:
  /Users/tianwenliang/.agents/skills/ominicrawl
可在 config.yaml 用 `project_root:` 一行覆盖。

目录结构 (全部在 project_root 下):
  media/        媒体统一落 $VAULT/media（与 publish_vault 体系一致），不再落技能目录
  logs/         subscription_log.md / .fetch.log / batch_log.md
  state/        .subscription-crawl-cache.json(去重状态)
  notes/        中间 md 笔记: notes/<platform>/<blogger>/
  daily/        fetch_inbox_links 的日记源链接目录
  inbox/        notes/inbox (单条 URL 抓取)
  watchlist.md  订阅名单(用户维护)
  credentials/  feishu.json / zhipu.json (项目级凭证副本)

迁移期兜底: legacy_media_dir() 指向旧 steven_vault/media, 仅用于读取旧图。
"""
import os
import json
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent


def _load_config() -> dict:
    cfg_path = SKILL_DIR / "config.yaml"
    if cfg_path.exists():
        try:
            import yaml
            return yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
    return {}


_CFG = _load_config()


def _expand(p: str) -> Path:
    return Path(os.path.expanduser(p)).resolve()


# ── 唯一根目录 ────────────────────────────────────────────────────────
def project_root() -> Path:
    return _expand(
        _CFG.get("project_root")
        or str(Path.home() / ".agents" / "skills" / "crawl")
    )


# 旧 vault(仅迁移期兜底读取, 不写入)
LEGACY_VAULT = Path.home() / "Documents" / "steven_vault"


# ── 子目录访问器(全部派生自 project_root) ──────────────────────────────
def media_dir() -> Path:
    """媒体统一落 $VAULT/media（与 publish_vault 体系一致），不再落技能目录。
    VAULT 环境变量可覆盖，默认 ~/Documents/steven_vault。"""
    _vault = Path(os.environ.get("VAULT", str(Path.home() / "Documents" / "steven_vault")))
    return _vault / "media"


def logs_dir() -> Path:
    return project_root() / "logs"


def state_dir() -> Path:
    return project_root() / "state"


def notes_dir() -> Path:
    return project_root() / "notes"


def daily_dir() -> Path:
    """fetch_inbox_links 的日记源链接目录"""
    return project_root() / "daily"


def inbox_dir() -> Path:
    """单条 URL 抓取(inbox 模式)落盘目录"""
    return notes_dir() / "inbox"


def credentials_dir() -> Path:
    """项目级凭证目录(飞书 / 智谱)"""
    return project_root() / "credentials"


def cache_file() -> Path:
    """去重状态 json"""
    return state_dir() / ".subscription-crawl-cache.json"


def sub_log() -> Path:
    """抓取汇总日志 subscription_log.md"""
    return logs_dir() / "subscription_log.md"


def fetch_log() -> Path:
    """逐条抓取信号 .fetch.log"""
    return logs_dir() / ".fetch.log"


def batch_log() -> Path:
    """批量处理日志 batch_log.md"""
    return logs_dir() / "batch_log.md"


def watchlist() -> Path:
    return project_root() / "watchlist.md"


def legacy_media_dir() -> Path:
    return LEGACY_VAULT / "media"


# ── 向后兼容别名(部分旧脚本引用, 统一返回 project_root) ──
def get_cache_root() -> Path:
    return project_root()


def get_data_root() -> Path:
    return project_root()


# ── 凭证解析(项目级优先, 系统级兜底) ───────────────────────────────────
def zhipu_api_key() -> str:
    """返回智谱 API Key; 取不到返回空串"""
    candidates = [
        credentials_dir() / "zhipu.json",
        Path.home() / ".agents" / "credentials" / "ominicrawl" / "zhipu.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8")).get("api_key", "")
            except Exception:
                continue
    return ""


# ── 便捷: 确保目录存在 ─────────────────────────────────────────────────
def ensure_dirs() -> None:
    for d in (project_root(), media_dir(), logs_dir(), state_dir(),
              notes_dir(), daily_dir(), credentials_dir(), inbox_dir()):
        d.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    print("project_root  :", project_root())
    print("media_dir     :", media_dir())
    print("notes_dir     :", notes_dir())
    print("state_dir     :", state_dir())
    print("logs_dir      :", logs_dir())
    print("cache_file    :", cache_file())
    print("sub_log       :", sub_log())
    print("fetch_log     :", fetch_log())
    print("batch_log     :", batch_log())
    print("watchlist     :", watchlist())
    print("daily_dir     :", daily_dir())
    print("inbox_dir     :", inbox_dir())
    print("credentials   :", credentials_dir())
    print("legacy_media  :", legacy_media_dir())
