CTL=s3://annotationprod/cad-disk-extract/_control/z3conv/db1/v2/_box
OUT=s3://bim-proprietary-data/cad-disk-extract/_work/db1_v2
mkdir -p /opt/v2/bc && cd /opt/v2/bc
pip3 install -q ifcopenshell==0.8.4.post1 > pip.log 2>&1 || pip3 install -q ifcopenshell >> pip.log 2>&1
python3 -c "import ifcopenshell; print(ifcopenshell.version)"
aws s3 cp --quiet $CTL/boltcat.py . && aws s3 cp --quiet $CTL/boltcat_keys_disk12.json .
aws s3 cp --quiet s3://bim-proprietary-data/cad-disk-extract/zentitude-data-4/_control/conv/ifc/jobs.json d4ifc.json
aws s3 cp --quiet s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/conv/ifc/jobs.json d3ifc.json
python3 - <<'PY'
import json
k = json.load(open('boltcat_keys_disk12.json'))
for fn in ('d4ifc.json', 'd3ifc.json'):
    try:
        J = json.load(open(fn)); J = J if isinstance(J, list) else J.get('jobs', [])
        k += [j['input_key'] for j in J if j.get('input_key') and (j.get('size') or 0) < 300e6 and j['input_key'].lower().endswith('.ifc')]
    except Exception as e: print('jobs', fn, e)
print('keys', len(k)); json.dump(k, open('keys.json', 'w'))
PY
python3 boltcat.py keys.json boltcat.jsonl 8 2500 &
P=$!
while kill -0 $P 2>/dev/null; do sleep 120; aws s3 cp --quiet boltcat.jsonl $OUT/boltcat.jsonl; done
aws s3 cp --quiet boltcat.jsonl $OUT/boltcat.jsonl
echo finished
