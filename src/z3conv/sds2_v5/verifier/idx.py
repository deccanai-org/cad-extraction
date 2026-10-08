"""index the data-3 SDS2 fleet results: id, name, version, chosen, class, corpus, step key/bytes/solids, job size"""
import json, boto3, concurrent.futures as cf
s3 = boto3.Session(profile_name='bim').client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
P = 'cad-disk-extract/zenitude-data-3/_state/conv/sds2/results/'
keys = []
for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=P):
    keys += [o['Key'] for o in pg.get('Contents', []) if o['Key'].endswith('.json')]
def one(k):
    try:
        d = json.loads(s3.get_object(Bucket=B, Key=k)['Body'].read())
    except Exception as e:
        return dict(key=k, err=str(e))
    m = d.get('manifest') or {}; st = d.get('step') or {}
    return dict(id=d.get('id'), name=d.get('name'), version=d.get('version'), chosen=d.get('chosen'), status=d.get('status'),
                cls=m.get('class'), corpus=m.get('corpus'), conv=m.get('converter'), step_key=st.get('key'), step_bytes=st.get('bytes'),
                solids=st.get('solids'), stage=st.get('stage'), size=d.get('size'), prefix=(d.get('outputs') or {}).get('prefix'),
                files=(d.get('outputs') or {}).get('files'), alts=sorted((d.get('alternatives') or {}).keys()))
with cf.ThreadPoolExecutor(12) as ex:
    rows = list(ex.map(one, keys))
json.dump(rows, open('fleet_index.json', 'w'))
print(len(rows))
