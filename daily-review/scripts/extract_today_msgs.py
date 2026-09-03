#!/usr/bin/env python3
"""
extract_today_msgs.py — daily-review skill 辅助脚本 (Dedalus/dsh 会话复盘)

数据源: ~/.dsh/sessions/**/session.jsonl.zstd (dsh 自身压缩会话记录)
- 每个会话一个 zstd 压缩的 JSONL, 每行一个事件
- user/message   → 用户消息 (data.content[].text)
- assistant/message → 助手消息 (data.message.content[] 中 type=text 的 text)
- time 为毫秒时间戳, 按 CST 目标日期过滤
- 剔除注入式上下文 (runtime context / system-reminder / skills 说明等), 保留真实对话

用法:
    python3 extract_today_msgs.py                 # 今天
    python3 extract_today_msgs.py 2026-09-01      # 指定日期
    python3 extract_today_msgs.py 2026-09-01 --out /path/to/out.md   # 指定输出
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SESSIONS_ROOT = Path.home() / '.dsh' / 'sessions'

# 注入式上下文特征 (user 消息, 非用户真言, 抽取时剔除)
_INJECT_MARKERS = [
    'Current runtime context.',
    'MNEMON RUNTIME MEMORY SNAPSHOT',
    '<system-reminder>',
    '<runtime-memory-file',
    'You are an AI agent powered by',
    'The DeepSeek Harness implementation checkout is at',
    'Paths prefixed with @ are files explicitly referenced',
    '<skill_content',
    'MNEMON ROUTES (quoted routing data',
]

def get_vault_path():
    """vault 根目录: 优先 $VAULT, 其次常用路径"""
    env = os.environ.get('VAULT', '').strip()
    if env:
        return Path(env)
    for p in [Path.home() / 'Documents' / 'steven_vault',
              Path.home() / 'webdav' / 'steven_vault']:
        if p.exists():
            return p
    return Path.home() / 'webdav' / 'steven_vault'


def ms_to_cst(ms):
    """毫秒时间戳 → CST datetime"""
    cst = datetime.timezone(datetime.timedelta(hours=8))
    return datetime.datetime.fromtimestamp(ms / 1000, tz=cst)


def find_session_files():
    """扫描 ~/.dsh/sessions/ 下所有 session JSONL (zstd 压缩或明文)"""
    if not SESSIONS_ROOT.exists():
        return []
    files = []
    for sub in SESSIONS_ROOT.iterdir():
        if not sub.is_dir():
            continue
        for p in sub.glob('*/session.jsonl.zstd'):
            files.append(p)
        for p in sub.glob('*/session.jsonl'):
            files.append(p)
    return files


def decompress(fp: Path):
    """解压 session 文件 → 逐行 JSON 对象迭代"""
    raw = fp.read_bytes()
    if fp.name.endswith('.zstd'):
        try:
            proc = subprocess.run(['zstd', '-d', '-c', str(fp)],
                                  capture_output=True, timeout=60)
            raw = proc.stdout
        except Exception as e:
            print(f"# WARN: 解压失败 {fp}: {e}", file=sys.stderr)
            return
    for line in raw.decode('utf-8', errors='replace').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def is_inject(text: str) -> bool:
    """判断是否为注入式上下文"""
    t = text.strip()
    if not t:
        return True
    for m in _INJECT_MARKERS:
        if t.startswith(m):
            return True
    return False


def extract_msg_text(content) -> str:
    """从消息 content 提取纯文本 (text 类型)"""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ''
    parts = []
    for it in content:
        if isinstance(it, dict) and it.get('type') == 'text':
            parts.append(it.get('text', ''))
    return '\n'.join(parts)


def extract_session(fp: Path, start_ms: int, end_ms: int):
    """从单个 session 文件提取目标时间窗内的 user/assistant 消息"""
    msgs = []  # (time_ms, role, text)
    for o in decompress(fp):
        tp = o.get('type')
        if tp not in ('user/message', 'assistant/message'):
            continue
        t = o.get('time')
        if not isinstance(t, (int, float)):
            continue
        if t < start_ms or t >= end_ms:
            continue
        d = o.get('data') or {}
        if tp == 'user/message':
            text = extract_msg_text(d.get('content'))
            if not text or is_inject(text):
                continue
            # 只保留真实用户来源
            src = (d.get('source') or {}).get('kind')
            if src and src not in ('user', 'human'):
                continue
            msgs.append((t, 'user', text))
        else:  # assistant/message
            m = d.get('message') or {}
            if m.get('role') != 'assistant':
                continue
            text = extract_msg_text(m.get('content'))
            if text:
                msgs.append((t, 'assistant', text))
    return msgs


def extract_day(target_date: datetime.date):
    """提取目标日期全部 dsh 会话消息 → list[dict(session, cwd, msgs)]"""
    cst = datetime.timezone(datetime.timedelta(hours=8))
    day_start = datetime.datetime.combine(target_date, datetime.time(0, 0), tzinfo=cst)
    day_end = day_start + datetime.timedelta(days=1)
    start_ms = int(day_start.timestamp() * 1000)
    end_ms = int(day_end.timestamp() * 1000)

    sessions = []
    for fp in find_session_files():
        msgs = extract_session(fp, start_ms, end_ms)
        if not msgs:
            continue
        msgs.sort(key=lambda x: x[0])
        # 会话标题: 取第一个 session 事件的 cwd
        cwd = ''
        try:
            for o in decompress(fp):
                if o.get('type') == 'session':
                    cwd = o.get('cwd', '') or ''
                    break
        except Exception:
            pass
        sessions.append({
            'file': fp,
            'cwd': cwd,
            'msgs': msgs,
        })
    sessions.sort(key=lambda s: s['msgs'][0][0])
    return sessions


def format_full(sessions, target_date):
    """生成完整流水 Markdown"""
    weekday = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][target_date.weekday()]
    n_msgs = sum(len(s['msgs']) for s in sessions)
    md = [f"# dsh 对话流水 — {target_date.isoformat()} {weekday}",
          "",
          f"> 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
          f"> 数据源: ~/.dsh/sessions · {len(sessions)} 个会话 · {n_msgs} 条消息",
          "",
          "---",
          ""]
    for i, s in enumerate(sessions, 1):
        t0 = ms_to_cst(s['msgs'][0][0]).strftime('%H:%M')
        t1 = ms_to_cst(s['msgs'][-1][0]).strftime('%H:%M')
        md.append(f"## 会话 #{i} ({t0}-{t1})")
        if s['cwd']:
            md.append("")
            md.append(f"`cwd: {s['cwd']}`")
        md.append("")
        for t, role, text in s['msgs']:
            hhmm = ms_to_cst(t).strftime('%H:%M')
            icon = '👤' if role == 'user' else '🤖'
            if len(text) > 2000:
                text = text[:2000] + f"\n\n…[截断, 共 {len(text)} 字]"
            md.append(f"**{icon} {role}** ({hhmm})")
            md.append("")
            md.append(text)
            md.append("")
        md.append("---")
        md.append("")
    return '\n'.join(md)


def main():
    parser = argparse.ArgumentParser(description='提取 dsh 当日会话对话流水')
    parser.add_argument('date', nargs='?', help='YYYY-MM-DD (默认今天)')
    parser.add_argument('--out', help='输出文件路径 (默认写入 vault 04_agent/conversation/)')
    parser.add_argument('--print-only', action='store_true', help='只打印, 不写文件')
    args = parser.parse_args()

    if args.date:
        target = datetime.date.fromisoformat(args.date)
    else:
        target = datetime.date.today()

    sessions = extract_day(target)
    print(f"# 目标日期: {target.isoformat()} · 找到 {len(sessions)} 个会话", file=sys.stderr)
    for s in sessions:
        print(f"#   - {s['file'].parent.name} ({len(s['msgs'])} msgs)", file=sys.stderr)

    md = format_full(sessions, target)

    if args.print_only:
        print(md)
        return

    if args.out:
        out = Path(args.out)
    else:
        vault = get_vault_path()
        out_dir = vault / '04_agent' / 'conversation'
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{target.isoformat()}.md"
    out.write_text(md, encoding='utf-8')
    print(f"# 已写入: {out}", file=sys.stderr)
    print(md)


if __name__ == '__main__':
    main()