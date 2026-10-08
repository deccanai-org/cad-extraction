#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/diag_far.py $W/job/diag_far.py
cd $W
P=/opt/conv/env/bin/python
tail -3 $W/diag/far2_c131.err $W/diag/far2_6f3c.err
timeout 250 $P $W/job/diag_far.py $W/job/ifc2step6_dev3.py $W/in/4f6b8e2e96937507.bin 0Dcno5GC10KvAeo5hL2xEF > $W/diag/far3_4f6b.jsonl 2> $W/diag/far3_4f6b.err
python3 -c "
import json,glob
for fn in sorted(glob.glob('$W/diag/far3_*.jsonl')):
    for l in open(fn):
        r=json.loads(l)
        for k in ('tc','kernel_poly','kernel_tri'):
            v=r.get(k)
            if isinstance(v,dict):
                for var in ('in_place','shifted','mapped_translation'):
                    x=v[var]; print(r['gid'], k, var, x['verdict'], x['brepcheck'], 'translated_copy', x.get('translated_copy'), 'tol', x.get('max_tol'))
"
