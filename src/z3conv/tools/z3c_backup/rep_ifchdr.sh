#!/bin/bash
# READ-ONLY: header of every distinct IFC file shipped in the packages (first 16 KB): FILE_NAME time_stamp + originating_system /
# preprocessor, FILE_SCHEMA -> authoring software and year range for the report. Output /opt/report/out/ifc_headers.json.
export AWS_DEFAULT_REGION=ap-south-1
D=/opt/report; O=$D/out
if systemctl is-active -q z3repifc; then echo running; tail -n 2 $O/ifchdr.log; exit 0; fi
if [ -f $O/ifc_headers.json ]; then echo finished; tail -n 3 $O/ifchdr.log; exit 0; fi
cat > $D/rep_ifchdr.py <<'PYEOF'
import json, re, collections, zipfile, io
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=96, retries={'max_attempts': 8, 'mode': 'standard'}))
B = 'bim-proprietary-data'; PK = 'cad-disk-extract/dataset/packages/3d/'
P = json.load(open('/opt/report/out/projects_t2.json'))
rows = {}
def man(pid):
    m = s3.get_object(Bucket=B, Key=f'{PK}{pid}/manifest.jsonl')['Body'].read().decode('utf-8', 'surrogateescape')
    out = []
    for l in m.split('\n'):
        if '"model/ifc/' in l:
            r = json.loads(l)
            if r['relpath'].startswith('model/ifc/'): out.append((pid, r['relpath'], r['sha256'], r['bytes'], r.get('modality')))
    return out
with ThreadPoolExecutor(32) as tp:
    for lst in tp.map(man, [p['id'] for p in P if (p['per_channel'].get('model/ifc') or 0) > 0]):
        for pid, rp, sha, b, mo in lst: rows.setdefault(sha, (pid, rp, b, mo))
print('distinct ifc', len(rows), flush=True)
rx_name = re.compile(r"FILE_NAME\s*\((.*?)\);", re.S | re.I); rx_schema = re.compile(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']*)'", re.I)
def one(item):
    sha, (pid, rp, b, mo) = item
    try:
        if mo == 'ifczip' or rp.lower().endswith('.ifczip'):
            return sha, {'project_id': pid, 'zip': True, 'disk': pid.split('__')[0]}
        hdr = s3.get_object(Bucket=B, Key=f'{PK}{pid}/{rp}', Range='bytes=0-16383')['Body'].read().decode('latin1')
        m = rx_name.search(hdr); sc = rx_schema.search(hdr)
        f = re.findall(r"'((?:[^']|'')*)'", m.group(1)) if m else []
        ts = next((x for x in f if re.match(r'\d{4}-\d{2}-\d{2}', x)), None)
        # FILE_NAME(name, time_stamp, (author), (organization), preprocessor_version, originating_system, authorization)
        return sha, {'project_id': pid, 'disk': pid.split('__')[0], 'time_stamp': ts, 'fields': f[:8], 'schema': sc.group(1) if sc else None, 'bytes': b}
    except Exception as e:
        return sha, {'project_id': pid, 'error': str(e)[:100]}
res = {}
with ThreadPoolExecutor(64) as tp:
    for i, (sha, r) in enumerate(tp.map(one, rows.items()), 1):
        res[sha] = r
        if i % 2000 == 0: print(i, flush=True)
json.dump(res, open('/opt/report/out/ifc_headers.json', 'w'))
print('DONE', len(res), flush=True)
PYEOF
systemctl reset-failed z3repifc 2>/dev/null
systemd-run --unit=z3repifc --collect --working-directory=$D --setenv=AWS_DEFAULT_REGION=ap-south-1 /bin/bash -c \
  "/opt/report/venv/bin/python $D/rep_ifchdr.py > $O/ifchdr.log 2>&1; echo rc=\$? >> $O/ifchdr.log"
sleep 30; echo "started: $(systemctl is-active z3repifc)"; tail -n 2 $O/ifchdr.log
