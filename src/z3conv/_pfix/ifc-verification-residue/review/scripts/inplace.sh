#!/bin/bash
# in-place OCC read-back (fleet step_check with its far rule switched off) of the rvF (6.1.4) and rvP (6.1.4+farall) STEPs of the far models
W=/work/agentwork/ifc-verification-residue-review; cd $W; PY=/opt/conv/env/bin/python
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-verification-residue-review
mkdir -p inplace; sed "s/^if far_points and far_first is not None and not mk\['MAPPED_ITEM('\]:/if False:/" kitF/step_check.py > inplace/step_check_inplace.py
grep -c "^if False:" inplace/step_check_inplace.py > inplace/patched.txt
run() { l=$1; i=$2; s=w/$l/$i/out.step; [ -f $s ] || return; timeout 3000 $PY inplace/step_check_inplace.py $s inplace/${l}_$i.json > /dev/null 2>&1; }
N=0
for i in e7f6f3e68d0ed451 925e43c7b39a340c 4f6b8e2e96937507 e747269a560d4ab0 59f3aa6220928ebd f582bf9375d82ab7 342f2352feaa8a44 ffd8d7272b6cdecf bf768f1f03f316a1 77056eeaac10628d aa1e8467bb71402e d528e0ccedbb0c8f 9df308a46bf9aac7 c685065ec108c24b c8689f1be0c133a0 f451e1f2a8116bec; do
  for l in rvF rvP; do run $l $i & N=$((N+1)); [ $((N % 4)) -eq 0 ] && wait; done
done
wait
$PY - <<'EOP' > inplace/summary.txt
import json, glob, os
for f in sorted(glob.glob('inplace/rv*_*.json')):
    k = json.load(open(f)); print(os.path.basename(f)[:-5], 'roots', k.get('roots'), 'solids', k.get('solids'), 'valid', k.get('valid'), 'invalid', k.get('invalid'), 'empty_roots', k.get('empty_roots'), 'far_rule_used', k.get('translated_for_check_mm'))
EOP
aws s3 cp --quiet inplace/summary.txt $R/analysis/inplace_summary.txt; aws s3 cp --quiet inplace/patched.txt $R/analysis/inplace_patched.txt
