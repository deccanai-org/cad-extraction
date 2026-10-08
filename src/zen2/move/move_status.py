"""move_status.py - summarise the annotationprod -> bim move from the state in the destination bucket (bim profile, read-only)."""
import json, sys, time, boto3
from concurrent.futures import ThreadPoolExecutor
from botocore.config import Config
s3 = boto3.Session(profile_name='bim').client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 30, 'mode': 'standard'}))
B, P = 'bim-proprietary-data', 'cad-disk-extract/'
def keys(pre):
    out, tok = [], None
    while True:
        kw = dict(Bucket=B, Prefix=pre)
        if tok: kw['ContinuationToken'] = tok
        r = s3.list_objects_v2(**kw); out += [o['Key'] for o in r.get('Contents', [])]
        if not r.get('IsTruncated'): return out
        tok = r['NextContinuationToken']
def get(k):
    try: return json.loads(s3.get_object(Bucket=B, Key=k)['Body'].read())
    except Exception: return None
plan = get(P + '_control/move/plan.json')
if not plan:
    print('plan: not ready'); sys.exit()
res = keys(P + '_state/move/results/'); cl = keys(P + '_state/move/claims/')
with ThreadPoolExecutor(32) as ex: rs = [r for r in ex.map(get, res) if r]
tot = {k: sum(r.get(k, 0) for r in rs) for k in ('objects', 'bytes', 'verified', 'mismatch', 'shard_errors')}
print(f"{time.strftime('%H:%M:%SZ', time.gmtime())} chunks {len(rs)}/{plan['chunks']} (claimed {len(cl)}) shards {plan['shards']} | "
      f"objects {tot['objects']:,} ({tot['bytes']/1e12:.2f} TB) verified {tot['verified']:,} mismatch {tot['mismatch']} shard_errors {tot['shard_errors']}")
