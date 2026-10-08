#!/bin/bash
# V6_FAR_ALWAYS unset: patched converter vs fleet 6.1.4, STEP body (header lines dropped) md5 + stats levels
W=/work/agentwork/ifc-verification-residue-review; cd $W; mkdir -p offid; PY=/opt/conv/env/bin/python
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-verification-residue-review
export DEFLECTION=0.005 ANG_DEFLECTION=0.6 V6_FAR_VERIFY=1 V6_VERIFY_PROCS=2
unset V6_FAR_ALWAYS
: > offid/summary.txt
for i in 4f6b8e2e96937507 925e43c7b39a340c e747269a560d4ab0 59f3aa6220928ebd aa1e8467bb71402e b0dd43ef3a3fdb69 f2c1e8d84b309c52 ffd8d7272b6cdecf; do
  for c in 614 614far; do
    o=offid/${i}_$c.step
    timeout 1200 $PY job/ifc2step6_$c.py in/$i.bin $o --mode hybrid --prec 2 --threads 2 > offid/${i}_$c.log 2>&1
    echo "$i $c rc=$? body=$(grep -v '^FILE_NAME\|^FILE_DESCRIPTION\|ifc2step6 6.1' $o | md5sum | cut -c1-12) bytes=$(stat -c %s $o) levels=$($PY -c "import json;print(json.load(open('$o.stats.json')).get('levels'))")" >> offid/summary.txt
  done
done
aws s3 cp --quiet offid/summary.txt $R/analysis/offident_summary.txt
