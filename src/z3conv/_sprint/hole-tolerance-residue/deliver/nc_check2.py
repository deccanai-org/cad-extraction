"""nc_check2.py NC_FIND_JSON OUT_JSON : Tekla DSTV NC files next to each model -> hole diameters, weighted by the ST quantity:
BO holes (diameter > 0; 0-diameter entries with the 'm' suffix are punch marks) + IK inner contours that are circles (all arc radii equal,
extent 2r) - Tekla writes large holes as IK contours."""
import json, sys, os, re, collections, boto3, concurrent.futures as cf
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
R = json.load(open(sys.argv[1])); out = {}
num = lambda x: float(re.sub(r'[a-z]+$', '', x) or 0)


def keys_of(prefix):
    ks = []; tok = None
    while True:
        kw = dict(Bucket=B, Prefix=prefix, MaxKeys=1000)
        if tok: kw['ContinuationToken'] = tok
        r = s3.list_objects_v2(**kw)
        ks += [o['Key'] for o in r.get('Contents', []) if o['Key'].lower().endswith(('.nc1', '.nc'))]
        if not r.get('IsTruncated'): return ks
        tok = r['NextContinuationToken']


def parse(txt):
    L = txt.replace('\r', '').split('\n'); q = 1
    try:
        i = L.index('ST'); hdr = [l.strip() for l in L[i + 1:i + 26] if not l.strip().startswith('**')]; q = int(float(hdr[5]))
    except Exception:
        pass
    bo = []; ik = []; blk = None; cur = []; contours = []
    for l in L:
        s = l.strip()
        if re.fullmatch(r'[A-Z]{2}', s):
            if blk == 'IK' and cur: contours.append(cur)
            blk = s; cur = []; continue
        if not s: continue
        t = s.split()
        if blk == 'BO' and t[0] in ('v', 'o', 'u', 'h') and len(t) >= 4:
            try:
                dd = num(t[3])
                if dd > 0: bo.append(round(dd, 2))
            except ValueError:
                pass
        elif blk == 'IK':
            if t[0] in ('v', 'o', 'u', 'h'):
                if cur: contours.append(cur)
                cur = []; t = t[1:]
            try: cur.append([num(x) for x in t])
            except ValueError: pass
    for c in contours:
        rs = {round(abs(v[2]), 2) for v in c if len(v) > 2 and v[2] != 0}
        if len(rs) == 1 and all(len(v) > 2 and v[2] != 0 for v in c[:-1]):
            r = rs.pop(); xs = [v[0] for v in c]; ys = [v[1] for v in c]
            if abs(max(max(xs) - min(xs), max(ys) - min(ys)) - 2 * r) < 0.1:
                ik.append(round(2 * r, 2))
    return q, bo, ik


for h, v in R.items():
    lv = next((x for k, x in v.items() if x.get('nc')), None)
    if not lv: continue
    ks = [k for d in lv['nc_dirs'] for k in keys_of(d + '/') if os.path.dirname(k) == d]
    bo = collections.Counter(); ik = collections.Counter(); nf = 0
    def get(k):
        try: return s3.get_object(Bucket=B, Key=k)['Body'].read().decode('latin-1')
        except Exception: return None
    with cf.ThreadPoolExecutor(16) as ex:
        for txt in ex.map(get, ks):
            if txt is None: continue
            nf += 1; q, b, c = parse(txt)
            for x in b: bo[f'{x:g}'] += q
            for x in c: ik[f'{x:g}'] += q
    out[h] = {'dirs': lv['nc_dirs'], 'files': nf, 'bo_holes': dict(bo.most_common()), 'ik_circles': dict(ik.most_common())}
    print(h[:12], nf, 'BO', dict(bo.most_common(10)), 'IK', dict(ik.most_common(6)), flush=True)
json.dump(out, open(sys.argv[2], 'w'), indent=1)
