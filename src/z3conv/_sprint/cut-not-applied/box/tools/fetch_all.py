"""fetch_all.py OUTDIR [max_mb] : download every DB1 source of data/db1_all.json (sha256-verified)"""
import sys, os, json, hashlib, boto3, concurrent.futures as cf
s3 = boto3.client('s3', region_name='ap-south-1')
A = json.load(open('data/db1_all.json')); out = sys.argv[1]; mx = float(sys.argv[2]) if len(sys.argv) > 2 else 1e9
os.makedirs(out, exist_ok=True)
def get(o):
    p = os.path.join(out, o['id'][:16] + '.db1')
    if not o.get('input_key'): return o['id'][:16], 'no_key'
    if (o.get('size') or 0) > mx * 1e6: return o['id'][:16], 'too_big'
    if os.path.exists(p) and os.path.getsize(p) == o.get('size'): return o['id'][:16], 'cached'
    try:
        s3.download_file('bim-proprietary-data', o['input_key'], p + '.part')
        h = hashlib.sha256(open(p + '.part', 'rb').read()).hexdigest()
        if h != o['sha256']: return o['id'][:16], 'sha_mismatch ' + h[:12]
        os.rename(p + '.part', p); return o['id'][:16], 'ok'
    except Exception as e:
        return o['id'][:16], 'error ' + str(e)[:100]
import collections
c = collections.Counter()
with cf.ThreadPoolExecutor(12) as ex:
    for r in ex.map(get, A):
        c[r[1].split()[0]] += 1
        if r[1] not in ('ok', 'cached'): print(*r)
print(dict(c))
