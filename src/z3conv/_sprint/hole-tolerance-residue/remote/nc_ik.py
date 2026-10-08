import json, sys, re, boto3, collections
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
R = json.load(open('nc_find.json'))
h = [k for k in R if k.startswith(sys.argv[1])][0]
lv = next((x for k, x in R[h].items() if x.get('nc')), None)
ks = []
for d in lv['nc_dirs']:
    r = s3.list_objects_v2(Bucket=B, Prefix=d + '/', MaxKeys=1000)
    ks += [o['Key'] for o in r.get('Contents', []) if o['Key'].lower().endswith(('.nc1', '.nc')) and o['Key'].rsplit('/', 1)[0] == d]
shown = 0; circ = collections.Counter(); circq = collections.Counter(); nik = 0
for k in ks:
    txt = s3.get_object(Bucket=B, Key=k)['Body'].read().decode('latin-1').replace('\r', '')
    L = txt.split('\n'); blk = None; cur = []; contours = []
    hdr = []; 
    try:
        i = L.index('ST'); hdr = [l.strip() for l in L[i + 1:i + 26] if not l.strip().startswith('**')]; q = int(float(hdr[5]))
    except Exception:
        q = 1
    for l in L:
        s = l.strip()
        if re.fullmatch(r'[A-Z]{2}', s):
            if blk == 'IK' and cur: contours.append(cur)
            blk = s; cur = []; continue
        if blk == 'IK' and s:
            t = s.split()
            if t[0] in ('v', 'o', 'u', 'h'):
                if cur: contours.append(cur)
                cur = []; t = t[1:]
            vals = [float(re.sub(r'[a-z]+$', '', x) or 0) for x in t]
            cur.append(vals)
    for c in contours:
        nik += 1
        rs = sorted({round(abs(v[2]), 2) for v in c if len(v) > 2 and v[2] != 0})
        xs = [v[0] for v in c]; ys = [v[1] for v in c]
        key = f'radii={rs} bbox={round(max(xs)-min(xs),1):g}x{round(max(ys)-min(ys),1):g} pts={len(c)}'
        circ[key] += 1; circq[key] += q
        if shown < 3 and rs:
            print(k.rsplit('/', 1)[1], c); shown += 1
print('IK contours', nik)
for k, v in circq.most_common(15): print(v, circ[k], k)
