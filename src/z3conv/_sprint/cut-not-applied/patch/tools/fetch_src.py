"""fetch_src.py JOBS.json OUTDIR ID_PREFIX... : download the source DB1s (by job id prefix, or 'all') and verify sha256"""
import sys, os, json, hashlib, boto3, concurrent.futures as cf
s3 = boto3.client('s3', region_name='ap-south-1')
J = json.load(open(sys.argv[1])); out = sys.argv[2]; want = sys.argv[3:]
os.makedirs(out, exist_ok=True)
sel = [j for j in J if 'all' in want or any(j['id'].startswith(w) for w in want)]
def get(j):
    p = os.path.join(out, j['id'][:16] + '.db1')
    if os.path.exists(p) and os.path.getsize(p) == j.get('size'):
        return j['id'][:16], 'cached'
    try:
        s3.download_file('bim-proprietary-data', j['input_key'], p + '.part')
        h = hashlib.sha256(open(p + '.part', 'rb').read()).hexdigest()
        if h != j['sha256']:
            return j['id'][:16], 'sha_mismatch'
        os.rename(p + '.part', p); return j['id'][:16], 'ok'
    except Exception as e:
        return j['id'][:16], 'error ' + str(e)[:120]
with cf.ThreadPoolExecutor(8) as ex:
    for r in ex.map(get, sel): print(*r)
print('selected', len(sel))
