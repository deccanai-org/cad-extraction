#!/bin/bash
cd /work/agentwork/sds2-recall-nc1
timeout 50 /opt/conv/env/bin/python - <<'PY'
import json, collections, boto3
s3 = boto3.client('s3', region_name='ap-south-1')
st = json.load(open('inv/steps.json'))
c = collections.Counter()
ex = {}
for jid, d in st.items():
    e = d.get('v4c')
    if e:
        k = e['step']; pre = '/'.join(k.split('/')[:3]); c[pre] += 1; ex.setdefault(pre, k)
print(c.most_common(10))
for pre, k in ex.items():
    try:
        h = s3.head_object(Bucket='bim-proprietary-data', Key=k); print('OK', h['ContentLength'], k[:150])
    except Exception as e:
        print('MISSING', k[:150], str(e)[:80])
PY
tail -3 logs/d12b.log
