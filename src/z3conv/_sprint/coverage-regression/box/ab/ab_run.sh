#!/bin/bash
# coverage-regression A/B on BOX-B: deployed code-i kit (kit_i) vs kit_fix (db1bolts guard + overlay ext for reused models)
SLUG=coverage-regression
W=/work/agentwork/$SLUG/ab
OUTS=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/$SLUG
PY=/opt/conv/env/bin/python
cd $W
up() { aws s3 cp --only-show-errors "$1" "$OUTS/ab/$(basename $1)"; }
mkdir -p kit_i && aws s3 cp --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/db1/ kit_i/ --exclude "*/*" --only-show-errors
rm -rf kit_fix && cp -r kit_i kit_fix && cp db1bolts.py kit_fix/db1bolts.py
md5sum kit_i/*.py kit_i/*.json > kit_i.md5
$PY build_ovl_ext.py ovl_models.json kit_i/tekla_profiles_overlay.json overlay_ext.json tekla_profiles_overlay.merged.json > build_ovl.log 2>&1
cp tekla_profiles_overlay.merged.json kit_fix/tekla_profiles_overlay.json
md5sum kit_fix/*.py kit_fix/*.json > kit_fix.md5
for f in build_ovl.log overlay_ext.json kit_i.md5 kit_fix.md5; do up $f; done
# phase 1: decode only, both kits (fast)
ls jobs/*.json | xargs -P 6 -I{} sh -c "$PY ab_one.py kit_i dec_i {} decode; $PY ab_one.py kit_fix dec_fix {} decode" > phase1.log 2>&1
up phase1.log
# phase 2: full pipeline (decode + ifc2step6 + read-back + census + join) on kit_fix, then kit_i for the overlay models
ls jobs/*.json | xargs -P 4 -I{} sh -c "$PY ab_one.py kit_fix full_fix {} full" > phase2.log 2>&1
up phase2.log
echo ALLDONE >> phase2.log; up phase2.log
