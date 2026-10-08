import json, sys, re, boto3, collections
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
R = json.load(open('nc_find.json'))
h = [k for k in R if k.startswith(sys.argv[1])][0]
lv = next((x for k, x in R[h].items() if x.get('nc')), None)
ks = []
for d in lv['nc_dirs']:
    r = s3.list_objects_v2(Bucket=B, Prefix=d + '/', MaxKeys=1000)
    ks += [o['Key'] for o in r.get('Contents', []) if o['Key'].lower().endswith(('.nc1', '.nc')) and o['Key'].rsplit('/', 1)[0] == d]
shown0 = 0; ik_d = collections.Counter(); blocks = collections.Counter()
for k in ks:
    txt = s3.get_object(Bucket=B, Key=k)['Body'].read().decode('latin-1').replace('\r', '')
    L = txt.split('\n'); blk = None; ik = []
    for l in L:
        s = l.strip()
        if re.fullmatch(r'[A-Z]{2}', s):
            if blk == 'IK' and ik:
                xs = [p[0] for p in ik]; ys = [p[1] for p in ik]
                ik_d[f'{round(max(xs) - min(xs), 1):g}x{round(max(ys) - min(ys), 1):g} n={len(ik)}'] += 1
            blk = s; blocks[s] += 1; ik = []; continue
        if blk == 'IK' and s:
            t = s.split()
            try:
                ik.append((float(re.sub(r'[a-z]+$', '', t[1])), float(re.sub(r'[a-z]+$', '', t[2]))))
            except Exception:
                pass
        if blk == 'BO' and s and shown0 < 12:
            t = s.split()
            try:
                if float(re.sub(r'[a-z]+$', '', t[3])) == 0:
                    print(k.rsplit('/', 1)[1], repr(l)); shown0 += 1
            except Exception:
                print('unparsed', k.rsplit('/', 1)[1], repr(l)); shown0 += 1
print('blocks', dict(blocks))
print('IK contours (bbox x/y, points):', ik_d.most_common(15))
