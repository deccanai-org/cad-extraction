set -e
cd /work/agentwork/class1-readiness-audit
aws s3 cp --recursive --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/class1-readiness-audit/ ./job/
PY=/opt/conv/env/bin/python
$PY job/prefetch.py job/ids.json || true
rm -rf kit_k2 && mkdir -p kit_k2 && aws s3 cp --recursive --only-show-errors --exclude 'fixes/*' --exclude 'v2/*' s3://annotationprod/cad-disk-extract/_control/z3conv/db1/ kit_k2/
cp job/htr_db1bolts.py kit_k2/db1bolts.py; cp job/htr_db1step.py kit_k2/db1step.py
$PY job/build_cat.py src job/ids.json kit_k2/bolt_catalog.json cat_c1.json
$PY job/apply_c1_patch.py kit_k2 cat_c1.json
$PY job/apply_c1_stats.py kit_k2
$PY job/audit_patch.py kit_k2
md5sum kit_k2/db1bolts.py kit_k2/db1step.py kit_k2/db1bolts2.py kit_k2/bolt_catalog.json | cut -c1-12
aws s3 cp --only-show-errors cat_c1.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/class1-readiness-audit/cat_c1.json
aws s3 cp --only-show-errors cat_c1.json.vs_old.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/class1-readiness-audit/cat_c1.vs_old.json
SMALL_FIRST=1 setsid nohup $PY job/aud.py kit_k2 k2 job/ids.json 8 > aud_k2.log 2>&1 < /dev/null &
echo started $!
