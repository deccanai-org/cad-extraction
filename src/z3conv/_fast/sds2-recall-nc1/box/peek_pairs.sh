#!/bin/bash
cd /work/agentwork/sds2-recall-nc1
ls -la inv/pairs*.json
timeout 100 /opt/conv/env/bin/python - <<'PY'
import json, collections
P = json.load(open('inv/pairs_orig.json'))
rows = []
for jid, o in P.items():
    if not o['steps']: continue
    nf = [e for e in o['nc1_files'] if e['rel'] in ('inside_job','sibling','same_project')]
    res = sum(1 for e in nf if e.get('key'))
    ifc = [(h['rel'][:5], round(h['size']/1e6,1)) for h in o['ifc'][:3]]
    labs = {l: round((e.get('step_size') or 0)/1e6) for l, e in o['steps'].items()}
    rows.append((o['name'][:34], jid[:8], labs, len(nf), res, len(o['nc1_sets']), ifc))
rows.sort(key=lambda r: -r[3])
for r in rows: print(r)
PY
