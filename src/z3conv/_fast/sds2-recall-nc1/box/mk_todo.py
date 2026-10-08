#!/usr/bin/env python3
"""conversion targets: paired jobs with ground truth (NC1 parts with holes kept for the job, or an IFC export of the job)
that have exactly one of the two labels (v4c / v5.x): convert the missing one (v5.3 or v4c)."""
import json, os, sys, collections
W = '/work/agentwork/sds2-recall-nc1'
sel = json.load(open(os.path.join(W, 'inv', 'nc1_sel.json')))
min_holes = int(sys.argv[1]) if len(sys.argv) > 1 else 10
max_gb = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
todo = []; c = collections.Counter()
for jid, r in sel.items():
    if r.get('error'):
        continue
    labs = set(r.get('labels') or [])
    gt = (r.get('parts_kept_with_holes') or 0) >= min_holes or bool(r.get('ifc_candidates'))
    if not gt or not labs:
        c['skip_no_gt_or_no_step'] += 1; continue
    if (r.get('model_bytes') or 0) > max_gb * 1e9:
        c['skip_big'] += 1; continue
    has5 = any(l.startswith('v5') for l in labs if not l.endswith('_not_accepted'))
    if 'v4c' in labs and 'v5.3' not in labs:
        todo.append([jid, 'v5.3']); c['v5.3'] += 1
    if has5 and 'v4c' not in labs:
        todo.append([jid, 'v4c']); c['v4c'] += 1
json.dump(todo, open(os.path.join(W, 'inv', 'conv_todo.json'), 'w'))
print(dict(c), len(todo))
