#!/bin/bash
cd /work/agentwork/sds2-recall-nc1
timeout 60 /opt/conv/env/bin/python - <<'PY'
import json, glob
for pat in ('7699a4a7*', '4d7a8a6f*6687d2a0*'):
    for f in sorted(glob.glob('out/ifc/' + pat + '.json')):
        r = json.load(open(f))
        print('=' * 90); print(r['job'], r['label'], r.get('ifc_path', '')[-90:])
        print(' reg', json.dumps(r.get('registration'))[:400])
        print(' overall', json.dumps(r.get('overall')))
        print(' excluded', r.get('ifc_excluded_non_physical'), 'ifc products', r.get('ifc_products'), 'step solids', r.get('step_solids'))
        print(' recall', json.dumps({k: [v['n'], v['matched'], v['near_only_3tol']] for k, v in r['recall_by_ifc_role'].items()})[:900])
        print(' prec', json.dumps({k: [v['n'], v['matched'], v.get('n_in_ifc_coverage'), v.get('precision_in_ifc_coverage')] for k, v in r['precision_by_step_kind'].items()})[:700])
        print(' unmatched ifc', json.dumps(r.get('unmatched_ifc_top', [])[:5])[:900])
        print(' unmatched step', json.dumps(r.get('unmatched_step_top', [])[:5])[:900])
        print(' overlap', json.dumps(r.get('plan_overlap')))
PY
