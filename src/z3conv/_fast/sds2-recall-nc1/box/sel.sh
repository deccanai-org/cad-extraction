#!/bin/bash
cd /work/agentwork/sds2-recall-nc1
timeout 60 /opt/conv/env/bin/python - <<'PY'
import json, glob, os
seen = set()
for f in sorted(glob.glob('out/nc1/*.json')):
    d = json.load(open(f))
    s = d.get('summary') or d
    jid = s.get('job_id') or s.get('id')
    if jid in seen: continue
    seen.add(jid)
    sel = s.get('nc1_selection') or {}
    print((s.get('job') or s.get('name') or '')[:40], '| kept', sel.get('parts_kept'), '/', sel.get('parts_total'), '| names', [n[:30] for n in sel.get('job_names', [])][:4])
    print('     orders', [(o[0][:34], o[1], o[2]) for o in sel.get('orders', [])[:6]])
PY
