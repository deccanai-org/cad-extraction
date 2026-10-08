set -e
cd /work/agentwork/class1-readiness-audit
PY=/opt/conv/env/bin/python
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/class1-readiness-audit/build_cat.py job/
$PY job/build_cat.py src job/ids.json kit_k/bolt_catalog.json cat_c2.json
aws s3 cp --only-show-errors cat_c2.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/class1-readiness-audit/cat_c2.json
aws s3 cp --only-show-errors cat_c2.json.vs_old.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/class1-readiness-audit/cat_c2.vs_old.json
rm -rf kit_k3 && cp -r kit_k2 kit_k3 && cp cat_c2.json kit_k3/bolt_catalog.json
$PY - <<'P'
import json
a=json.load(open('cat_c1.json'))['models']; b=json.load(open('cat_c2.json'))['models']
ids=[j for j in json.load(open('job/ids.json')) if j['sha256'] in b and (j['sha256'] not in a)]
json.dump(ids, open('ids_k3.json','w')); print(len(ids), 'models with a newly built own catalog')
P
SMALL_FIRST=1 setsid nohup $PY job/aud.py kit_k3 k3 ids_k3.json 6 > aud_k3.log 2>&1 < /dev/null &
echo started $!
