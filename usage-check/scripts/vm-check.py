#!/usr/bin/env python3
# vm-check.sh - VM disk/memory/CPU via SSH, outputs JSON
import json, subprocess, re, sys

def run_ssh(cmd):
    result = subprocess.run(
        ['ssh', '-o', 'ConnectTimeout=10', '-o', 'StrictHostKeyChecking=no', '-o', 'BatchMode=yes',
         'ubuntu@175.178.210.156', cmd],
        capture_output=True, text=True, timeout=20
    )
    return result.stdout + result.stderr

# Disk
lines = run_ssh('df -BG /').strip().split('\n')
row = lines[-1].split()
dt = int(row[1].rstrip('G'))
du_ = int(row[2].rstrip('G'))
da = int(row[3].rstrip('G'))
dp = int(row[4].rstrip('%'))

# Memory
m = run_ssh('free -m').strip().split('\n')
for l in m:
    if l.startswith('Mem:'):
        pm = l.split()
        mt = int(pm[1]); mu = int(pm[2])
        ma = int(pm[6]); mp = round(mu/mt*100, 1)

# CPU
t = run_ssh('top -bn1 -d1').strip().split('\n')
cp = 0.0
for l in t:
    if 'Cpu(s)' in l:
        m_idle = re.search(r'([0-9.]+)\s+id', l)
        if m_idle:
            idle = float(m_idle.group(1))
            cp = round(100 - idle, 1)
        break

# Load
load = run_ssh('uptime').strip()
m2 = re.search(r'load average: (.+)', load)
la = m2.group(1).strip() if m2 else ''

# Time
fetched_at = subprocess.check_output(['date', '+%Y-%m-%d %H:%M:%S']).decode().strip()

def h(v, thresholds):
    for n, s in thresholds:
        if v >= n: return s
    return thresholds[-1][1]

dh = h(dp, [(90,'紧急'),(75,'紧张'),(50,'正常'),(0,'充足')])
mh = h(mp, [(90,'紧急'),(75,'紧张'),(50,'正常'),(0,'充足')])
ch = h(cp, [(90,'紧急'),(70,'紧张'),(30,'正常'),(0,'充足')])
de = '\U0001f7e8' if dp>=90 else '\U0001f534' if dp>=75 else '\U0001f7e1' if dp>=50 else '\U0001f7e2'
me = '\U0001f7e8' if mp>=90  else '\U0001f534' if mp>=75  else '\U0001f7e1' if mp>=50  else '\U0001f7e2'
ce = '\U0001f7e8' if cp>=90  else '\U0001f534' if cp>=70  else '\U0001f7e1' if cp>=30  else '\U0001f7e2'

out = {
    'disk':   {'total_gb': dt, 'used_gb': du_, 'avail_gb': da, 'used_percent': dp, 'health': dh, 'health_emoji': de},
    'memory': {'total_mb': mt, 'used_mb': mu, 'avail_mb': ma, 'used_percent': mp, 'health': mh, 'health_emoji': me},
    'cpu':    {'used_percent': cp, 'load_avg': la, 'health': ch, 'health_emoji': ce},
    'host': '175.178.210.156',
    'fetched_at': fetched_at
}
print(json.dumps(out, ensure_ascii=False))
