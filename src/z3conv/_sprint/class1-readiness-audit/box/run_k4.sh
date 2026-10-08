set -e
cd /work/agentwork/class1-readiness-audit
PY=/opt/conv/env/bin/python
pkill -f "job/aud.py kit_k3 " || true; sleep 1; pkill -f "kit_k3/convert_one.py" || true
aws s3 cp --recursive --only-show-errors --exclude "*" --include "*.py" --include "*.patch" s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/class1-readiness-audit/ ./job/
rm -rf kit_k4 kit_k4e && mkdir -p kit_k4 && aws s3 cp --recursive --only-show-errors --exclude 'fixes/*' --exclude 'v2/*' s3://annotationprod/cad-disk-extract/_control/z3conv/db1/ kit_k4/
cp job/htr_db1bolts.py kit_k4/db1bolts.py; cp job/htr_db1step.py kit_k4/db1step.py
$PY job/build_cat.py src job/ids.json kit_k/bolt_catalog.json cat_c3.json
BOLTCAT_ENV=1 $PY job/build_cat.py src job/ids.json kit_k/bolt_catalog.json cat_c3env.json
$PY job/apply_c1_patch.py kit_k4 cat_c3.json; $PY job/apply_c1_stats.py kit_k4; $PY job/audit_patch.py kit_k4
cp -r kit_k4 kit_k4e; cp cat_c3env.json kit_k4e/bolt_catalog.json
for f in cat_c3.json cat_c3env.json; do aws s3 cp --only-show-errors $f s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/class1-readiness-audit/$f; done
$PY - <<'P'
import json
c=json.load(open('cat_c3.json')); e=json.load(open('cat_c3env.json'))
ids=json.load(open('job/ids.json'))
a=[j for j in ids if j['sha256'] in c['assdb_maps'] or j['sha256'] in c['models']]
b=[j for j in ids if j['sha256'] in e['models'] and j['sha256'] not in c['models']]
json.dump(a, open('ids_k4.json','w')); json.dump(b, open('ids_k4e.json','w')); print(len(a), 'k4 models (own assdb / catalog);', len(b), 'k4e models (env catalog only)')
P
md5sum kit_k4/db1bolts.py kit_k4/db1step.py kit_k4/db1bolts2.py kit_k4/bolt_catalog.json kit_k4e/bolt_catalog.json | cut -c1-12
SMALL_FIRST=1 setsid nohup $PY job/aud.py kit_k4 k4 ids_k4.json 6 > aud_k4.log 2>&1 < /dev/null &
SMALL_FIRST=1 setsid nohup $PY job/aud.py kit_k4e k4e ids_k4e.json 4 > aud_k4e.log 2>&1 < /dev/null &
echo started
