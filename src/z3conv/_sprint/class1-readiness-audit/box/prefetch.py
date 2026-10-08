"""prefetch.py IDS_JSON : the model folder's own catalogs (screwdb.db, assdb.db, profdb.bin) for every DB1 model -> src/<sha12>_sib/"""
import json, os, sys, boto3, concurrent.futures as cf
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
def one(j):
    sd = os.path.join('src', j['sha256'][:12] + '_sib'); os.makedirs(sd, exist_ok=True); pre = j['input_key'].rsplit('/', 1)[0] + '/'; got = []
    for s in j.get('siblings') or []:
        if s.lower() in ('screwdb.db', 'assdb.db', 'profdb.bin'):
            t = os.path.join(sd, s.lower())
            if not os.path.exists(t):
                try: s3.download_file(B, pre + s, t + '.part'); os.replace(t + '.part', t)
                except Exception as e: open(t + '.err', 'w').write(str(e)[:300]); continue
            got.append(s.lower())
    return j['sha256'][:12], got
with cf.ThreadPoolExecutor(8) as ex:
    res = list(ex.map(one, json.load(open(sys.argv[1]))))
print(sum(1 for _, g in res if 'screwdb.db' in g and 'assdb.db' in g), 'with screwdb+assdb;', sum(1 for _, g in res if 'profdb.bin' in g), 'with profdb')
