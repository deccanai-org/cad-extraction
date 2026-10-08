#!/bin/bash
# code j (deployed 23:45Z) A/B, decode only: kit_j (as deployed) vs kit_j_fix (db1bolts guard + worker best-of fix + overlay ext)
SLUG=coverage-regression
W=/work/agentwork/$SLUG/ab
OUTS=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/$SLUG
PY=/opt/conv/env/bin/python
cd $W
mkdir -p abj && aws s3 cp --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/$SLUG/abj/ abj/ --only-show-errors
rm -rf kit_j kit_j_fix && mkdir -p kit_j && aws s3 cp --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/db1/ kit_j/ --exclude "*/*" --only-show-errors
grep -n "^CODE" kit_j/worker.py
cp -r kit_j kit_j_fix && cp abj/db1bolts.py abj/worker.py abj/tekla_profiles_overlay.json kit_j_fix/
md5sum kit_j/*.py kit_j/*.json > kit_j.md5; md5sum kit_j_fix/*.py kit_j_fix/*.json > kit_j_fix.md5
ls jobs/*.json | xargs -P 6 -I{} sh -c "$PY ab_one.py kit_j dec_j {} decode; $PY ab_one.py kit_j_fix dec_jfix {} decode" > phasej.log 2>&1
for f in phasej.log kit_j.md5 kit_j_fix.md5; do aws s3 cp --only-show-errors $f $OUTS/ab/$f; done
echo DONEJ >> phasej.log; aws s3 cp --only-show-errors phasej.log $OUTS/ab/phasej.log
