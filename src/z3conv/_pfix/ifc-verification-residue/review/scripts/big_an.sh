#!/bin/bash
W=/work/agentwork/ifc-verification-residue-review; cd $W; PY=/opt/conv/env/bin/python
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-verification-residue-review
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue-review/chg_parts.py job/chg_parts.py
i=557c5bc89f708d1e
( timeout 2400 $PY inplace/step_check_inplace.py w/rvF_big/$i/out.step inplace/rvF_big_$i.json > /dev/null 2>&1 ) &
( timeout 2400 $PY inplace/step_check_inplace.py w/rvP_big/$i/out.step inplace/rvP_big_$i.json > /dev/null 2>&1 ) &
timeout 600 $PY job/cmp_rv.py rvF_big rvP_big > cmp_big.txt 2>&1
aws s3 cp --quiet cmp_big.txt $R/analysis/cmp_big.txt
CHG_MAX=400 timeout 3000 $PY job/chg_parts.py rvF_big rvP_big $i > chg_big.jsonl 2> chg_big.err
aws s3 cp --quiet chg_big.jsonl $R/analysis/chg_big.jsonl; aws s3 cp --quiet chg_big.err $R/analysis/chg_big.err
wait
$PY -c "
import json
for l in ('rvF_big','rvP_big'):
    k=json.load(open('inplace/%s_557c5bc89f708d1e.json'%l)); print(l, 'in place: roots', k.get('roots'), 'solids', k.get('solids'), 'valid', k.get('valid'), 'invalid', k.get('invalid'), 'empty', k.get('empty_roots'))
" > inplace_big.txt 2>&1
aws s3 cp --quiet inplace_big.txt $R/analysis/inplace_big.txt
