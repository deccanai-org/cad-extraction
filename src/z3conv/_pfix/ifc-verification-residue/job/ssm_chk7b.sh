#!/bin/bash
W=/work/agentwork/ifc-verification-residue
wc -c $W/diag/far6_7b35.jsonl
python3 -c "
import json
for l in open('$W/diag/far6_7b35.jsonl'):
    r=json.loads(l)
    for k in ('tc','kernel_poly','kernel_tri'):
        v=r.get(k)
        if isinstance(v,dict): print(r['gid'], r['name'], k, 'in_place', v['in_place']['verdict'], '| shifted', v['shifted']['verdict'], '| mapped', v['mapped_translation']['verdict'])
        elif v: print(r['gid'], k, v)
    print({k:r[k] for k in r if k.endswith('_err')})
"
