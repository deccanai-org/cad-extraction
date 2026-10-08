#!/bin/bash
cd /work/agentwork/sds2-recall-nc1
timeout 60 /opt/conv/env/bin/python - <<'PY'
import json, glob
for pat in ('30ff95cd*', '6e9e3214*', 'ea3edfb6*'):
    for f in sorted(glob.glob('out/ifc/' + pat + '.json'))[:1]:
        r = json.load(open(f))
        print('=' * 80); print(r['job'], r['label'], r.get('ifc_path', '')[-70:])
        rr = r['recall_by_ifc_role']
        print(' cols', {k: [v['n'], v['matched'], v['near_only_3tol']] for k, v in rr.items() if 'Column' in k or 'Beam' in k})
        for g in r.get('unmatched_ifc_top', []):
            if 'Column' in g['role']:
                print(' UNM', g['role'], g['section'], g['n'], json.dumps(g['examples'][:2])[:500])
        for g in r.get('unmatched_step_top', [])[:12]:
            if g['cls'] in ('member_main', 'rolled_other'):
                print(' STEP-UNM', g['cls'], g['section'], g['n'], json.dumps(g['examples'][:1])[:300])
PY
