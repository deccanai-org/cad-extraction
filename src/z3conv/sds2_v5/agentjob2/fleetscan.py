"""Latest SDS2 stage-2 manifest per data-3 job: skipped reasons, approx stand-ins, family weight ratios. -> fleetscan.json"""
import json, re, collections, boto3
from concurrent.futures import ThreadPoolExecutor
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
P = 'cad-disk-extract/zenitude-data-3/conversions/sds2-step/'
keys = collections.defaultdict(list)
for page in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=P):
    for o in page.get('Contents', []):
        k = o['Key']
        if k.endswith('_stage2_manifest.json'):
            rest = k[len(P):].replace('_not_accepted/', '')
            jid, lab = rest.split('/')[:2]
            keys[jid].append((lab, k))
order = lambda l: [int(x) for x in re.findall(r'\d+', l)]
latest = {j: sorted(v, key=lambda x: order(x[0]))[-1] for j, v in keys.items()}
def one(item):
    jid, (lab, k) = item
    try:
        m = json.loads(s3.get_object(Bucket=B, Key=k)['Body'].read())
    except Exception:
        return None
    w = m.get('weight_check') or {}
    fam = {f: v for f, v in (w.get('by_family') or {}).items() if v.get('ratio') is not None and abs(v['ratio'] - 1) > 0.05 and v.get('sds2_lb', 0) > 200}
    return dict(id=jid, label=lab, version=m.get('version'), cls=m.get('class'), corpus=m.get('corpus'), ratio=w.get('ratio'),
                skipped=(m.get('skipped') or {}).get('by_reason'), standins=(m.get('standins') or {}).get('by_type'),
                fam_out=fam, approx=(m.get('counts') or {}).get('pieces_approx'), placed=(m.get('counts') or {}).get('placed_pieces'),
                reasons=m.get('class_reasons'))
with ThreadPoolExecutor(32) as ex:
    R = [r for r in ex.map(one, latest.items()) if r]
json.dump(R, open('/work/agentwork/sds2v54/fleetscan.json', 'w'))
print(len(R))
