#!/usr/bin/env python3
"""
extract_today_msgs.py — daily-review skill 辅助脚本 (Codex / WorkBuddy 双适配)

根据 --platform (codex|workbuddy|auto) 从不同数据源提取今日活动痕迹:

[对话数据源 — 按平台二选一]
  • codex     : ~/.codex/sessions/ + archived_sessions/ — Codex Desktop session JSONL
  • workbuddy : ~/.workbuddy/projects/*/<session-uuid>.jsonl — **本地同日完整对话全文**
                (对话发生时即落盘, 可做当日复盘, 无需 conversation_search 隔夜索引)
                文件名 uuid == sessions.id, 关联 workbuddy.db 的标题/调用技能。
                ⚠️ 旧版误以为"正文在服务端、本地只有元数据"是错的, 本地 JSONL 含全文。

[产物数据源 — 双平台共用] (产物落在 vault, 与创建它的 agent 无关)
  1. vault/04_agent/report/ — crawl 跑批报告
  2. vault/04_agent/huashu-ppt-snapshot-YYYYMMDD/ — huashu-design PPT 产物
  3. vault/subscription/ — 订阅目录 (MMDD-index.md + 数字目录新增)
  4. /tmp/codex_* 或 /tmp/workbuddy* — 工程目录 (按平台)
  5. ~/.codex/automations/*/ 或 WB 自动化 — heartbeat 配置 (按平台)
  6. vault git status — pending changes

用法:
    python3 extract_today_msgs.py                       # auto 检测平台
    python3 extract_today_msgs.py --platform workbuddy  # 显式 WB
    python3 extract_today_msgs.py 2026-07-29            # 指定日期
    python3 extract_today_msgs.py --products-only       # 只输出产物部分
"""

import argparse
import datetime
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path


# ---------- 路径解析 ----------

def get_vault_path():
    """vault 根目录: 优先 $VAULT, 否则 ~/Documents/steven_vault"""
    env = os.environ.get('VAULT', '').strip()
    if env:
        return Path(env)
    return Path.home() / 'Documents' / 'steven_vault'


# ---------- 平台检测 ----------

def detect_platform(explicit=None):
    """判断当前运行平台: 'codex' | 'workbuddy'

    优先级:
      1. 显式参数 --platform
      2. 环境变量: WB 设了 WORKBUDDY_APP_NAME / WORKBUDDY_CONFIG_DIR → workbuddy
      3. 数据存在性: ~/.codex/sessions 有 JSONL → codex; 否则 workbuddy
    """
    if explicit in ('codex', 'workbuddy'):
        return explicit
    if os.environ.get('WORKBUDDY_APP_NAME') or os.environ.get('WORKBUDDY_CONFIG_DIR'):
        return 'workbuddy'
    codex_sessions = Path.home() / '.codex' / 'sessions'
    if codex_sessions.exists() and any(codex_sessions.glob('rollout-*.jsonl')):
        return 'codex'
    # 默认兜底: 有 workbuddy.db 就当 workbuddy
    if wb_db_path().exists():
        return 'workbuddy'
    return 'codex'


def wb_db_path():
    """WorkBuddy 本地数据库路径"""
    cfg = os.environ.get('WORKBUDDY_CONFIG_DIR', '').strip()
    if cfg:
        p = Path(cfg) / 'workbuddy.db'
        if p.exists():
            return p
    return Path.home() / '.workbuddy' / 'workbuddy.db'


def ms_to_cst(ms):
    """毫秒时间戳 → CST datetime"""
    cst = datetime.timezone(datetime.timedelta(hours=8))
    return datetime.datetime.fromtimestamp(ms / 1000, tz=cst)


# ---------- WorkBuddy session 扫描 ----------

def extract_wb_sessions(target_date: datetime.date):
    """从 workbuddy.db 提取今日会话 (元数据级, 非全文)

    返回 list of dict:
      { 'time': 'HH:MM', 'title': str, 'skill': str|None,
        'mode': str|None, 'tokens': int|None, 'id': str }
    """
    db = wb_db_path()
    if not db.exists():
        return []
    cst = datetime.timezone(datetime.timedelta(hours=8))
    day_start = datetime.datetime.combine(target_date, datetime.time(0, 0), tzinfo=cst)
    day_end = day_start + datetime.timedelta(days=1)
    start_ms = int(day_start.timestamp() * 1000)
    end_ms = int(day_end.timestamp() * 1000)

    try:
        con = sqlite3.connect(str(db))
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        # 今日会话: 创建于今天, 或今天有活动 (last_activity_at / updated_at)
        cur.execute("""
            SELECT id, custom_title, title, created_at, updated_at,
                   last_activity_at, mode, model, plugin_context_json
            FROM sessions
            WHERE deleted_at IS NULL
              AND (
                (created_at >= ? AND created_at <= ?)
                OR (last_activity_at >= ? AND last_activity_at <= ?)
              )
            ORDER BY COALESCE(last_activity_at, created_at) ASC
        """, (start_ms, end_ms, start_ms, end_ms))
        rows = cur.fetchall()

        # token 用量 (session_usage)
        usage = {}
        try:
            cur.execute("SELECT session_id, used FROM session_usage")
            for r in cur.fetchall():
                usage[r['session_id']] = r['used']
        except sqlite3.Error:
            pass
        con.close()
    except sqlite3.Error as e:
        print(f"# WARN: 读取 workbuddy.db 失败: {e}", file=sys.stderr)
        return []

    sessions = []
    for r in rows:
        pc = json.loads(r['plugin_context_json'] or '{}')
        scenes = pc.get('microSceneIds', []) or []
        skill = None
        for s in scenes:
            if s.startswith('command://'):
                skill = s[len('command://'):]
                break
            elif s.startswith('skill://'):
                skill = s[len('skill://'):]
                break
        # 时间: 优先 last_activity_at, 否则 created_at
        t_ms = r['last_activity_at'] or r['created_at'] or r['updated_at']
        t_str = ms_to_cst(t_ms).strftime('%H:%M') if t_ms else '??:??'
        title = (r['custom_title'] or r['title'] or '').strip()
        sessions.append({
            'time': t_str,
            'title': title,
            'skill': skill,
            'mode': r['mode'],
            'tokens': usage.get(r['id']),
            'id': r['id'],
        })
    return sessions


# ---------- WorkBuddy 本地 JSONL 同日全文 ----------

# 注入式上下文标签 (非用户真言, 抽取时剔除)
_INJECT_TAGS = [
    'system-reminder', 'cb_summary', 'user_info', 'identity_context',
    'user_memory', 'product_identity', 'project_context', 'additional_data',
    'connector-status', 'memory_and_skills_reminder', 'working_memory_content',
    'automations', 'plugin-status',
]

def _strip_inject(text: str) -> str:
    """剔除注入式上下文块 (system-reminder / user_info / cb_summary ...), 保留用户真实提问"""
    for tag in _INJECT_TAGS:
        text = re.sub(r'<%s.*?</%s>' % (tag, tag), '', text, flags=re.S | re.I)
        # 也处理自闭合/无内容的情况
        text = re.sub(r'<%s\b[^>]*/?>' % tag, '', text, flags=re.I)
    # 解包用户真实提问标签 (只去标签, 保留内部文本)
    text = re.sub(r'</?user_query\b[^>]*>', '', text, flags=re.I)
    return text.strip()


def _extract_jsonl_text(o: dict) -> str:
    """从一条 JSONL 消息抽取纯文本 (input_text / output_text / 通用 text)"""
    c = o.get('content')
    if c is None:
        return ''
    if isinstance(c, str):
        text = c
    elif isinstance(c, list):
        parts = []
        for it in c:
            if isinstance(it, dict):
                t = it.get('type')
                if t in ('input_text', 'output_text'):
                    parts.append(it.get('text', ''))
                elif 'text' in it and it.get('text'):
                    parts.append(it['text'])
        text = '\n'.join(parts)
    else:
        return ''
    return _strip_inject(text)


def extract_wb_fulltext(target_date: datetime.date):
    """【WB 模式主对话源】从本地 JSONL 提取今日完整对话 (同上日即用, 无需 conversation_search)

    数据源: ~/.workbuddy/projects/<project>/<session-uuid>.jsonl
    - 对话在发生时即落盘, 可做**当日复盘**
    - timestamp 为毫秒时间戳, 按日期过滤
    - 文件名 uuid == sessions.id, 可关联标题/调用技能
    - 剔除 system-reminder / user_info / cb_summary 等注入块, 保留用户真实提问与助手回答

    返回 list of dict:
      { 'id', 'title', 'skill', 'mode', 'time_start', 'time_end', 'turns':[{role,text,ts}] }
    """
    projects_root = Path.home() / '.workbuddy' / 'projects'
    if not projects_root.exists():
        return []

    cst = datetime.timezone(datetime.timedelta(hours=8))
    day_start = datetime.datetime.combine(target_date, datetime.time(0, 0), tzinfo=cst)
    day_end = day_start + datetime.timedelta(days=1)
    start_ms = int(day_start.timestamp() * 1000)
    end_ms = int(day_end.timestamp() * 1000)

    # session 元数据 (标题/技能) 关联
    meta = {}
    db = wb_db_path()
    if db.exists():
        try:
            con = sqlite3.connect(str(db))
            con.row_factory = sqlite3.Row
            cur = con.cursor()
            cur.execute(
                "SELECT id, custom_title, title, plugin_context_json, mode "
                "FROM sessions WHERE deleted_at IS NULL"
            )
            for r in cur.fetchall():
                pc = json.loads(r['plugin_context_json'] or '{}')
                scenes = pc.get('microSceneIds', []) or []
                skill = None
                for s in scenes:
                    if s.startswith('command://'):
                        skill = s[len('command://'):]
                        break
                    elif s.startswith('skill://'):
                        skill = s[len('skill://'):]
                        break
                meta[r['id']] = {
                    'title': (r['custom_title'] or r['title'] or '').strip(),
                    'skill': skill,
                    'mode': r['mode'],
                }
            con.close()
        except sqlite3.Error:
            pass

    sessions = {}  # sid -> {'turns':[], 'first_ts':, 'last_ts':}
    for jf in projects_root.rglob('*.jsonl'):
        sid = jf.stem
        try:
            with open(jf, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        o = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = o.get('timestamp')
                    if not isinstance(ts, (int, float)):
                        continue
                    if ts < start_ms or ts >= end_ms:
                        continue
                    role = o.get('role')
                    if role not in ('user', 'assistant'):
                        continue
                    text = _extract_jsonl_text(o)
                    if not text:
                        continue
                    d = sessions.setdefault(sid, {'turns': [], 'first_ts': ts, 'last_ts': ts})
                    d['turns'].append({'role': role, 'text': text, 'ts': ts})
                    d['first_ts'] = min(d['first_ts'], ts)
                    d['last_ts'] = max(d['last_ts'], ts)
        except OSError:
            continue

    result = []
    for sid, d in sessions.items():
        m = meta.get(sid, {})
        result.append({
            'id': sid,
            'title': m.get('title') or '(未命名会话)',
            'skill': m.get('skill'),
            'mode': m.get('mode'),
            'time_start': ms_to_cst(d['first_ts']).strftime('%H:%M'),
            'time_end': ms_to_cst(d['last_ts']).strftime('%H:%M'),
            'turns': d['turns'],
        })
    result.sort(key=lambda x: x['time_start'])
    return result


# ---------- 1. Codex session 扫描 ----------

def find_today_jsonl(target_date: datetime.date):
    """扫描所有 Codex rollout JSONL 文件 (跨日 session 也接受)

    注意: 文件名日期 = session start date, 不等于事件日期. 跨日 session
    (例如 08-01 21:58 启动, 08-04 22:00 还有写) 不能按文件名过滤.
    这里扫描全部 session, 由 extract_conversation 按事件 timestamp 过滤.
    """
    candidates = []

    sessions_dir = Path.home() / '.codex' / 'sessions'
    if sessions_dir.exists():
        for p in sessions_dir.rglob('rollout-*.jsonl'):
            candidates.append(p)

    archived = Path.home() / '.codex' / 'archived_sessions'
    if archived.exists():
        for p in archived.glob('rollout-*.jsonl'):
            candidates.append(p)

    if not candidates:
        return []

    def get_timestamp(p):
        m = re.search(r'rollout-\d{4}-\d{2}-\d{2}T(\d{2})-(\d{2})-\d{2}', p.name)
        if m:
            return (int(m.group(1)), int(m.group(2)))
        return (0, 0)

    candidates = sorted(set(candidates), key=get_timestamp, reverse=True)
    return candidates


def is_valid_msg(text, role):
    """过滤系统消息"""
    if not text or len(text.strip()) < 5:
        return False
    skip_prefixes = [
        '<app-context>', '<permissions', '<collaboration',
        '<apps_instructions', '<plugins_instructions>',
        '<skills_instructions>', '# Codex desktop', '## Memory',
        '开始新会话时', 'The following is the Codex agent history',
        '<recommended_plugins>', '<environment_context>'
    ]
    for p in skip_prefixes:
        if text.startswith(p):
            return False
    return True


def extract_conversation(jsonl_paths, target_date=None):
    """从 JSONL 提取对话

    target_date: 若提供, 只保留事件 timestamp 落在 CST [date 00:00, date+1 00:00) 的事件.
    跨日 session 的事件按 timestamp 落 CST 日期, 不按文件名日期.
    """
    if target_date is None:
        target_date = datetime.date.today()
    cst = datetime.timezone(datetime.timedelta(hours=8))
    day_start = datetime.datetime.combine(target_date, datetime.time(0, 0), tzinfo=cst)
    day_end = day_start + datetime.timedelta(days=1)

    messages = []

    for fp in jsonl_paths:
        try:
            with open(fp, 'r') as f:
                for line in f:
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if d.get('type') != 'response_item':
                        continue

                    p = d.get('payload', {})
                    if p.get('type') != 'message':
                        continue

                    role = p.get('role', '')
                    if role not in ['user', 'assistant']:
                        continue

                    # 时戳过滤 (CST 当天)
                    ts = d.get('timestamp', '')
                    if ts:
                        try:
                            dt = datetime.datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone(cst)
                            if not (day_start <= dt < day_end):
                                continue
                        except ValueError:
                            pass

                    for c in p.get('content', []):
                        if c.get('type') in ['input_text', 'output_text']:
                            text = c.get('text', '').strip()
                            if is_valid_msg(text, role):
                                messages.append((role, text))
        except (OSError, IOError) as e:
            print(f"# WARN: cannot read {fp}: {e}", file=sys.stderr)

    return messages


def pair_conversation(messages):
    """配对用户-助手消息"""
    turns = []
    i = 0
    while i < len(messages):
        role, text = messages[i]
        if role == 'user':
            assistant_parts = []
            j = i + 1
            while j < len(messages) and messages[j][0] == 'assistant':
                assistant_parts.append(messages[j][1])
                j += 1
            turns.append({
                'user': text,
                'assistant': '\n\n'.join(assistant_parts) if assistant_parts else ''
            })
            i = j
        else:
            i += 1
    return turns


# ---------- 2-6. 产物反查 (新增) ----------

def fmt_size(n):
    """字节数 → 人类可读"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == 'B' else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def scan_crawl_report(vault: Path, target_date: datetime.date):
    """扫 vault/04_agent/report/crawl_op_YYYYMMDD.md"""
    ymd = target_date.strftime('%Y%m%d')
    p = vault / '04_agent' / 'report' / f'crawl_op_{ymd}.md'
    if not p.exists():
        return None
    # 解析前几行摘要
    try:
        text = p.read_text(encoding='utf-8')
    except Exception:
        return f"- `{p.name}` 存在但无法读取"
    # 提取关键数字
    summary = []
    m = re.search(r'(?:当日|实际)?入库(?:总篇数|篇数|)\s*[\|：:]?\s*(?:\*\*)?(\d+)(?:\*\*)?\s*篇?', text)
    if m:
        summary.append(f"入库 {m.group(1)} 篇")
    m = re.search(r'视频(?:帖|数)?\s*[\|：:]?\s*(?:\*\*)?(\d+)', text)
    if m:
        summary.append(f"视频 {m.group(1)}")
    m = re.search(r'Groq 请求次数\s*\|\s*(\d+)', text)
    if m:
        summary.append(f"Groq {m.group(1)} 次")
    m = re.search(r'转录成功\s*\|\s*(?:\*\*?)?(\d+)(?:\*\*?)?\s*\((\d+)%\)', text)
    if m:
        summary.append(f"转录成功 {m.group(1)}/{m.group(2)}%")
    size = p.stat().st_size
    return f"- `{p.relative_to(vault)}` ({fmt_size(size)}) — {', '.join(summary) if summary else '无关键数字'}"


def scan_ppt_snapshot(vault: Path, target_date: datetime.date):
    """扫 vault/04_agent/huashu-ppt-snapshot-YYYYMMDD/"""
    ymd = target_date.strftime('%Y%m%d')
    p = vault / '04_agent' / f'huashu-ppt-snapshot-{ymd}'
    if not p.exists():
        return None
    # 列出 v* 子目录
    versions = []
    for sub in sorted(p.iterdir()):
        if sub.is_dir() and sub.name.startswith('v'):
            try:
                mtime = datetime.datetime.fromtimestamp(sub.stat().st_mtime)
                size = sum(f.stat().st_size for f in sub.rglob('*') if f.is_file())
                versions.append(f"  - {sub.name} ({mtime.strftime('%H:%M')}, {fmt_size(size)})")
            except Exception:
                versions.append(f"  - {sub.name}")
    # 列根目录 pptx/pdf
    finals = []
    for f in sorted(p.iterdir()):
        if f.suffix in ('.pptx', '.pdf') and f.is_file():
            try:
                size = f.stat().st_size
                mtime = datetime.datetime.fromtimestamp(f.stat().st_mtime)
                finals.append(f"  - {f.name} ({mtime.strftime('%H:%M')}, {fmt_size(size)})")
            except Exception:
                finals.append(f"  - {f.name}")
    total_files = sum(1 for _ in p.rglob('*') if _.is_file())
    return (
        f"- `04_agent/{p.name}/` ({total_files} 文件)\n"
        + '\n'.join(versions[:10])
        + (f"\n  ... +{len(versions)-10} versions" if len(versions) > 10 else "")
        + (f"\n  平行产物:\n" + '\n'.join(finals[:5]) if finals else "")
    )


def scan_subscription(vault: Path, target_date: datetime.date):
    """扫 vault/subscription/MMDD-index.md + 数字目录新增"""
    mmdd = target_date.strftime('%m%d')
    p = vault / 'subscription' / f'{mmdd}-index.md'
    if not p.exists():
        return None
    # 统计今日 subscription 下修改/新建的 md 数
    today_md = 0
    sub_root = vault / 'subscription'
    if sub_root.exists():
        for f in sub_root.rglob('*.md'):
            try:
                mt = datetime.datetime.fromtimestamp(f.stat().st_mtime).date()
                if mt == target_date:
                    today_md += 1
            except Exception:
                pass
    size = p.stat().st_size
    return (
        f"- `subscription/{mmdd}-index.md` ({fmt_size(size)}) + "
        f"`subscription/**/*.md` 今日 {today_md} 个"
    )


def scan_tmp_work(target_date: datetime.date, platform='codex'):
    """扫 /tmp 工程目录 (按平台 + mtime 过滤 target_date)

    codex     : /tmp/codex_*, /tmp/codex_native*.pdf
    workbuddy : /tmp/workbuddy*
    """
    lines = []
    if platform == 'workbuddy':
        for d in sorted(Path('/tmp').glob('workbuddy*')):
            try:
                mt = datetime.datetime.fromtimestamp(d.stat().st_mtime)
                if mt.date() == target_date:
                    if d.is_dir():
                        lines.append(f"- `/tmp/{d.name}/` (mtime {mt.strftime('%H:%M')})")
                    else:
                        lines.append(f"- `/tmp/{d.name}` ({fmt_size(d.stat().st_size)}, {mt.strftime('%H:%M')})")
            except Exception:
                pass
        if not lines:
            return None
        return '\n'.join(lines)

    # --- codex 分支 ---
    # codex_ppt_build: 看 build.mjs / 各种 backup mtime 是否命中 target_date
    p = Path('/tmp/codex_ppt_build')
    if p.exists():
        # 收集该目录下所有 .mjs/.bak/.pre 文件中 mtime 命中 target_date 的
        any_match = False
        backups = []
        for f in p.iterdir():
            if f.is_file() and (f.suffix == '.mjs' or '.bak' in f.name or f.name.startswith('build.mjs.pre-')):
                try:
                    mt = datetime.datetime.fromtimestamp(f.stat().st_mtime)
                    if mt.date() == target_date:
                        any_match = True
                        if '.bak' in f.name or f.name.startswith('build.mjs.pre-'):
                            backups.append(f)
                except Exception:
                    pass
        if any_match:
            mjs_size = (p / 'build.mjs').stat().st_size if (p / 'build.mjs').exists() else 0
            lines.append(
                f"- `/tmp/codex_ppt_build/` — build.mjs {fmt_size(mjs_size)}, "
                f"{len(backups)} 个 backup/pre-fix 节点命中 {target_date}"
            )
    # codex_native*.pdf
    pdfs_today = []
    for pdf in Path('/tmp').glob('codex_native*.pdf'):
        try:
            mt = datetime.datetime.fromtimestamp(pdf.stat().st_mtime)
            if mt.date() == target_date:
                pdfs_today.append(pdf)
        except Exception:
            pass
    if pdfs_today:
        lines.append(
            f"- `/tmp/codex_native*.pdf` — {len(pdfs_today)} 个命中 {target_date}: "
            + ', '.join(p.name for p in pdfs_today)
        )
    # 其他 /tmp/codex* 目录
    for d in sorted(Path('/tmp').glob('codex*')):
        if d.is_dir() and d.name not in ('codex_ppt_build', 'codex-browser-use'):
            try:
                mt = datetime.datetime.fromtimestamp(d.stat().st_mtime)
                if mt.date() == target_date:
                    lines.append(f"- `/tmp/{d.name}/` (mtime {mt.strftime('%H:%M')})")
            except Exception:
                pass
    if not lines:
        return None
    return '\n'.join(lines)


def scan_automations(target_date: datetime.date, platform='codex'):
    """扫自动化配置 (按平台)

    codex     : ~/.codex/automations/*/automation.toml
    workbuddy : ~/.workbuddy/automations/*/memory.md (无 toml, 仅看今日改动的)
    """
    if platform == 'workbuddy':
        auto_dir = Path.home() / '.workbuddy' / 'automations'
        if not auto_dir.exists():
            return None
        lines = []
        for d in sorted(auto_dir.iterdir()):
            mem = d / 'memory.md'
            if not mem.exists():
                continue
            try:
                mt = datetime.datetime.fromtimestamp(mem.stat().st_mtime)
                if mt.date() == target_date:
                    lines.append(f"- `{d.name}` (memory.md 今日 {mt.strftime('%H:%M')} 改动)")
            except Exception:
                pass
        if not lines:
            return None
        return '\n'.join(lines)

    # --- codex 分支 ---
    auto_dir = Path.home() / '.codex' / 'automations'
    if not auto_dir.exists():
        return None
    lines = []
    for d in sorted(auto_dir.iterdir()):
        toml = d / 'automation.toml'
        if not toml.exists():
            continue
        try:
            mt = datetime.datetime.fromtimestamp(toml.stat().st_mtime)
            if mt.date() != target_date:
                continue
            text = toml.read_text(encoding='utf-8')
            m_id = re.search(r'^id\s*=\s*"([^"]+)"', text, re.M)
            m_kind = re.search(r'^kind\s*=\s*"([^"]+)"', text, re.M)
            m_status = re.search(r'^status\s*=\s*"([^"]+)"', text, re.M)
            m_target = re.search(r'^target_thread_id\s*=\s*"([^"]+)"', text, re.M)
            id_ = m_id.group(1) if m_id else d.name
            kind = m_kind.group(1) if m_kind else '?'
            status = m_status.group(1) if m_status else '?'
            target = (m_target.group(1)[:8] + '...') if m_target else '?'
            lines.append(f"- `{id_}` ({kind}, status={status}, target={target}) mtime={mt.strftime('%H:%M')}")
        except Exception:
            pass
    if not lines:
        return None
    return '\n'.join(lines)


def scan_vault_git_status(vault: Path, target_date: datetime.date):
    """扫 vault git status 简报 (修改/新增/删除)"""
    if not (vault / '.git').exists():
        return None
    try:
        result = subprocess.run(
            ['git', 'status', '--short'],
            cwd=vault, capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return None
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        if not lines:
            return "- 无未提交修改"
        # 简报: 按状态分组计数
        m_count = sum(1 for l in lines if l.startswith(' M') or l.startswith('M '))
        a_count = sum(1 for l in lines if 'A' in l[:2])
        d_count = sum(1 for l in lines if l.startswith(' D') or l.startswith('D '))
        untracked = sum(1 for l in lines if l.startswith('??'))
        return (
            f"- 未提交: M={m_count}, A={a_count}, D={d_count}, ??={untracked} (共 {len(lines)} 条)"
        )
    except Exception as e:
        return f"- git status 失败: {e}"


def scan_products(target_date: datetime.date, platform='codex'):
    """主扫描入口: 返回 Markdown 格式的产物摘要 (双平台共用 vault 数据)"""
    vault = get_vault_path()
    if not vault.exists():
        return "📦 今日产物\n\n- (vault 路径不存在)\n"

    sections = []
    sections.append(("crawl 跑批报告", scan_crawl_report(vault, target_date)))
    sections.append(("PPT 产物 (huashu)", scan_ppt_snapshot(vault, target_date)))
    sections.append(("subscription 订阅", scan_subscription(vault, target_date)))
    sections.append(("/tmp 工程痕迹", scan_tmp_work(target_date, platform)))
    sections.append(("heartbeat 自动化", scan_automations(target_date, platform)))
    sections.append(("vault git 状态", scan_vault_git_status(vault, target_date)))

    lines = [f"# 📦 今日产物 ({target_date.isoformat()})\n"]
    any_found = False
    for name, content in sections:
        if content:
            lines.append(f"## {name}\n{content}\n")
            any_found = True
        else:
            lines.append(f"## {name}\n- (无)\n")
    if not any_found:
        lines.append("\n*所有层均无产物*")
    return '\n'.join(lines)


# ---------- 主入口 ----------

def format_conversation(turns, target_date):
    """生成 Markdown 格式 (对话部分)"""
    weekday = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][
        target_date.weekday()
    ]

    md = f"""# Codex 对话记录 — {target_date.isoformat()} {weekday}

> 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
> 对话轮次: {len(turns)} 轮

---

"""
    for i, turn in enumerate(turns, 1):
        md += f"""## 对话 #{i}

### 👤 用户

{turn['user']}

---

### 🤖 助手

{turn['assistant'] or '*（无回复）*'}

---

"""
    return md


def format_wb_sessions(sessions, target_date):
    """生成 WorkBuddy 会话记录 Markdown (元数据级, 非全文)"""
    weekday = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][
        target_date.weekday()
    ]
    n = len(sessions)
    md = f"""# WorkBuddy 会话记录(元数据级, 已弃用) — {target_date.isoformat()} {weekday}

> ⚠️ 此函数已弃用: WB 模式改用 extract_wb_fulltext() 读本地 JSONL 同日全文
> 会话数: {n} 个 (数据源: workbuddy.db sessions 表 — 仅元数据)

---

"""
    for i, s in enumerate(sessions, 1):
        skill_line = f" · 调用: `{s['skill']}`" if s['skill'] else ""
        token_line = f" · tokens: {s['tokens']}" if s['tokens'] else ""
        mode_line = f" · 模式: {s['mode']}" if s['mode'] else ""
        md += f"""## 会话 #{i} — {s['time']}

### 💬 主题

{s['title']}{skill_line}{mode_line}{token_line}

### 🆔 session

`{s['id']}`

---

"""
    return md


def format_wb_fulltext(sessions, target_date):
    """生成 WorkBuddy 会话记录 Markdown (本地同日全文)"""
    weekday = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][
        target_date.weekday()
    ]
    n = len(sessions)
    total_turns = sum(len(s['turns']) for s in sessions)
    md = f"""# WorkBuddy 会话记录(全文) — {target_date.isoformat()} {weekday}

> 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
> 会话数: {n} 个 · 消息数: {total_turns} · 数据源: ~/.workbuddy/projects/*/<uuid>.jsonl (本地同日全文)
> ✅ 此源为**同日即落盘**的本地完整对话, 无需 conversation_search 隔夜索引

---

"""
    for i, s in enumerate(sessions, 1):
        skill_line = f" · 调用: `{s['skill']}`" if s['skill'] else ""
        mode_line = f" · 模式: {s['mode']}" if s['mode'] else ""
        md += (
            f"## 会话 #{i} — {s['time_start']}~{s['time_end']}\n\n"
            f"### 💬 主题\n\n{s['title']}{skill_line}{mode_line}\n\n"
            f"### 🆔 session\n\n`{s['id']}`\n\n---\n\n"
        )
        for t in s['turns']:
            icon = '👤' if t['role'] == 'user' else '🤖'
            txt = t['text']
            if len(txt) > 1500:
                txt = txt[:1500] + f"\n\n…[截断, 共 {len(t['text'])} 字]"
            md += (
                f"**{icon} {t['role']}** ({ms_to_cst(t['ts']).strftime('%H:%M')})\n\n"
                f"{txt}\n\n---\n\n"
            )
    return md


def main():
    parser = argparse.ArgumentParser(description='提取今日活动痕迹 (Codex/WorkBuddy 双适配)')
    parser.add_argument('date', nargs='?', help='YYYY-MM-DD (默认今天)')
    parser.add_argument('--platform', choices=['codex', 'workbuddy', 'auto'],
                        default='auto', help='数据源平台 (默认 auto 检测)')
    parser.add_argument('--products-only', action='store_true',
                        help='只输出产物部分, 不跑对话解析')
    args = parser.parse_args()

    if args.date:
        target = datetime.date.fromisoformat(args.date)
    else:
        target = datetime.date.today()

    platform = detect_platform(args.platform)
    print(f"# 平台: {platform}", file=sys.stderr)

    # 1. 产物扫描 (双平台共用 vault 数据)
    products_md = scan_products(target, platform)
    if args.products_only:
        print(products_md)
        return

    # 2. 对话扫描 (按平台)
    if platform == 'workbuddy':
        sessions = extract_wb_fulltext(target)
        print(f"# 找到 {len(sessions)} 个 WB 会话 (本地 JSONL 同日全文)", file=sys.stderr)
        conversation_md = format_wb_fulltext(sessions, target)
        conv_label = "WorkBuddy 会话(全文)"
        method_note = """---

## 🔍 摸排方法说明

本报告由 `extract_today_msgs.py` 自动生成 (WorkBuddy 模式), 包含两层数据:

1. **📦 今日产物** (优先) — vault 报告/快照/subscription + /tmp 工程 + 自动化配置 + git 状态
2. **WorkBuddy 会话(全文)** — `~/.workbuddy/projects/*/<session-uuid>.jsonl` 本地同日落盘的完整对话

✅ **数据源为本地 JSONL, 对话在发生时即写入, 可做当日复盘** (无需等 conversation_search 隔夜索引)。
完整消息含 user/assistant 文本; 注入式上下文 (system-reminder / user_info / cb_summary 等) 已剔除, 仅保留用户真实提问与助手回答。
LLM 总结时以**产物 + 当日全文**为准, 两者互补。
"""
    else:
        files = find_today_jsonl(target)
        if not files:
            print(f"# WARN: 无今日 ({target.isoformat()}) JSONL 文件", file=sys.stderr)
        print(f"# 读取 {len(files)} 个文件:", file=sys.stderr)
        for f in files[:5]:
            print(f"#   - {f.parent.name}/{f.name}", file=sys.stderr)
        messages = extract_conversation(files, target_date=target)
        turns = pair_conversation(messages)
        print(f"# 找到 {len(messages)} 条消息, {len(turns)} 个对话轮次", file=sys.stderr)
        conversation_md = format_conversation(turns, target)
        conv_label = "Codex 对话"
        method_note = """---

## 🔍 摸排方法说明

本报告由 `extract_today_msgs.py` 自动生成 (Codex 模式), 包含两层数据:

1. **📦 今日产物** (优先) — vault 报告/快照/subscription + /tmp 工程 + automation 配置 + git 状态
2. **Codex 对话** — Desktop 交互 session JSONL (user/assistant 文本)

⚠️ **重要**: Interactive Desktop session JSONL **不能** 反映:
- 自动化 Codex heartbeat runs (ominicrawl supervisor 等) 的真实工作
- 外部 skill (huashu-design 等) 通过非 Desktop 通道生成的产物
- /tmp 下的工程返工

LLM 总结时务必**以产物为准**, JSONL 仅作补充。
"""

    # 3. 输出: 产物在前, 对话在后 (产物优先, 避免漏判)
    full = products_md + "\n---\n\n" + conversation_md + "\n" + method_note
    print(full)


if __name__ == '__main__':
    main()
