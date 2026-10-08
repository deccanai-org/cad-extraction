import boto3, json, sys, glob, concurrent.futures as cf
s3 = boto3.Session(profile_name='bim').client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
engs = set(sys.argv[1].split(','))
rows = []
for f in glob.glob('../work/d4res/*.json'):
    r = json.load(open(f))
    if r.get('engine') in engs and r.get('status') == 'ok': rows.append(r)
rows.sort(key=lambda r: r.get('size') or 0)
def probe(r):
    key = r['input_key']; d = key.rsplit('/', 1)[0]; out = []
    n = 0
    for pg in s3.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=d + '/'):
        for o in pg.get('Contents', []):
            n += 1
            if o['Key'].lower().endswith('.ifc') and 20_000 < o['Size'] < 200_000_000:
                try: h = s3.get_object(Bucket=B, Key=o['Key'], Range='bytes=0-2000')['Body'].read().decode('latin1')
                except Exception: continue
                if 'Tekla' in h and 'GridExporter' not in h: out.append((o['Key'], o['Size']))
        if n > 5000: break
    return r, out
res = []
with cf.ThreadPoolExecutor(24) as ex:
    for r, out in ex.map(probe, rows[:int(sys.argv[2])]):
        if out:
            res.append(dict(engine=r['engine'], id=r['id'], size=r['size'], key=r['input_key'], ifc=out, members=(r.get('convert') or {}).get('members')))
            print(r['engine'], r['id'][:10], r['size'], (r.get('convert') or {}).get('members'), out[0][1], out[0][0][-80:], flush=True)
json.dump(res, open('ok_ifc_%s.json' % sys.argv[1].replace(',', '_'), 'w'), indent=1)
