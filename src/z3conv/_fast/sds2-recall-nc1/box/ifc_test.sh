#!/bin/bash
W=/work/agentwork/sds2-recall-nc1
cd $W && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-recall-nc1/sds2_ifc_recall.py sds2_ifc_recall.py.new && mv sds2_ifc_recall.py.new sds2_ifc_recall.py
timeout 110 /opt/conv/env/bin/python - <<'PY'
import json, os, sys, hashlib, glob
sys.path.insert(0, '/work/agentwork/sds2-recall-nc1')
W = '/work/agentwork/sds2-recall-nc1'
if not os.path.exists(W + '/inv/ifc_pairs.json'):
    P = json.load(open(W + '/inv/pairs.json'))
    import run_jobs
    out = {}
    for jid, o in P.items():
        ifcs = run_jobs.pick_ifcs(o)
        if ifcs:
            out[jid] = {'name': o['name'], 'steps': o['steps'], 'ifc': ifcs, 'paths': o['paths'][:2]}
    json.dump(out, open(W + '/inv/ifc_pairs.json', 'w'))
Q = json.load(open(W + '/inv/ifc_pairs.json'))
print(len(Q), 'jobs with IFC candidates')
import sds2_ifc_recall as R
n = 0
for jid, o in Q.items():
    for lab, e in o['steps'].items():
        cp = W + '/cache/step_' + hashlib.sha1(e['step'].encode()).hexdigest()[:16] + '.pkl'
        for h in o['ifc']:
            ic = W + f"/cache/ifc_{h['sha256'][:16]}.npz"
            if os.path.exists(cp) and os.path.exists(ic) and os.path.getsize(cp) < 3e8 and n < 2:
                n += 1
                r = R.run(e['step'], ic, 25.0, lab, o['name'], index_cache=cp)
                print(o['name'], lab, h['path'][-80:])
                print(json.dumps({k: r.get(k) for k in ('status', 'registration', 'overall', 'section_agreement_on_matched')}, default=str))
                print(json.dumps(r.get('recall_by_ifc_role'), default=str)[:1500])
                print(json.dumps(r.get('precision_by_step_kind'), default=str)[:800])
PY
