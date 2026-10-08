"""fetch_reports.py : for every data-3 DB1 job with Tekla report files beside it, download those files (same S3 folder) to reports/<id16>/"""
import os, re, json, boto3, concurrent.futures as cf
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
J = json.load(open('data/jobs.json'))
todo = []
for j in J:
    rep = [s for s in (j.get('siblings') or []) if re.search(r'\.(xsr|csv|rpt|xls|lst|txt)$', s, re.I)]
    if not rep: continue
    d = os.path.dirname(j['input_key'])
    for s in rep: todo.append((j['id'][:16], d + '/' + s, s))
def get(t):
    i, k, s = t
    os.makedirs(f'reports/{i}', exist_ok=True)
    p = f'reports/{i}/{s}'
    if os.path.exists(p): return 'cached'
    try:
        s3.download_file(B, k, p); return 'ok'
    except Exception as e:
        return 'err ' + str(e)[:60]
import collections
c = collections.Counter()
with cf.ThreadPoolExecutor(16) as ex:
    for r in ex.map(get, todo): c[r.split()[0]] += 1
print(dict(c), 'files', len(todo), 'models', len({t[0] for t in todo}))
