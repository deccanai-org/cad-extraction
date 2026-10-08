#!/bin/bash
cd /work/agentwork/audit-sds2-v5x
/opt/conv/env/bin/python - <<'PY'
import json, glob, re, os, collections
def lab(c):
    m = re.match(r'z3-sds2-(v[\d.]+?)-20\d\d', str(c or '')); return m.group(1) if m else None
C = collections.Counter(); first = {}
for f in sorted(glob.glob('s3/sds2/logs/*.log')):
    hp = os.path.basename(f)[:-4]
    t = open(f, errors='replace').read()
    m = re.search(r'^(\d\d:\d\d:\d\d) sds2 worker code=(\S+) (\S+)', t, re.M)
    code = lab(m.group(2)) if m else None; start = m.group(1) if m else None
    for k in re.findall(r'^\d\d:\d\d:\d\d WATCHDOG killed \w+ rss=\d+GB avail=\d+GB(.*)$', t, re.M):
        C[(code, k.strip() or '(no suffix)')] += 1
        first.setdefault((code, k.strip() or '(no suffix)'), []).append(start)
for k, v in sorted(C.items(), key=str): print(v, k, 'process starts', sorted(set(first[k]))[:3], '...', sorted(set(first[k]))[-3:])
# hosts heartbeats: which processes report rss (runtime with rss tracking)
H = [json.load(open(f)) for f in glob.glob('s3/sds2/hosts/*.json')]
c2 = collections.Counter((lab(h.get('code')), h.get('runtime'), any('rss' in r for r in h.get('running') or []) if h.get('running') else None) for h in H)
for k, v in sorted(c2.items(), key=str): print(v, k)
PY
