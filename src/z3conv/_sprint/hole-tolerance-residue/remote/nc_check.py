"""nc_check.py NC_FIND_JSON OUT_JSON : download the DSTV NC files found next to each model (model folder first, else parent) and tally the
hole diameters of their BO blocks (per file, and weighted by the ST quantity). Slotted holes (extra BO fields) counted separately."""
import json, sys, os, re, collections, boto3, concurrent.futures as cf
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
R = json.load(open(sys.argv[1])); out = {}


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
    lines = txt.replace('\r', '').split('\n')
    qty = 1; prof = None
    try:
        i = lines.index('ST')
        hdr = [l.strip() for l in lines[i + 1:i + 26] if not l.strip().startswith('**')]
        qty = int(float(hdr[5])); prof = hdr[6]
    except Exception:
        pass
    holes = []; blk = None
    for l in lines:
        s = l.strip()
        if re.fullmatch(r'[A-Z]{2}', s):
            blk = s; continue
        if blk == 'BO' and s:
            t = s.split()
            if t[0] in ('v', 'o', 'u', 'h') and len(t) >= 4:
                try:
                    d = float(re.sub(r'[a-z]+$', '', t[3]))
                    slot = len(t) > 5 and any(float(re.sub(r'[a-z]+$', '', x) or 0) != 0 for x in t[5:8])
                    holes.append((round(d, 2), slot))
                except ValueError:
                    pass
    return qty, prof, holes


for h, v in R.items():
    lv = next((x for k, x in v.items() if x.get('nc')), None)
    if not lv: continue
    dirs = list(lv['nc_dirs'])
    ks = [k for d in dirs for k in keys_of(d + '/') if os.path.dirname(k) == d]
    per = collections.Counter(); wtd = collections.Counter(); slots = collections.Counter(); nfile = 0
    def get(k):
        try: return k, s3.get_object(Bucket=B, Key=k)['Body'].read().decode('latin-1')
        except Exception as e: return k, None
    with cf.ThreadPoolExecutor(16) as ex:
        for k, txt in ex.map(get, ks):
            if txt is None: continue
            nfile += 1
            q, prof, holes = parse(txt)
            for d, sl in holes:
                per[f'{d:g}'] += 1; wtd[f'{d:g}'] += q
                if sl: slots[f'{d:g}'] += q
    out[h] = {'dirs': dirs, 'files': nfile, 'holes_per_file': dict(per.most_common()), 'holes_weighted_by_qty': dict(wtd.most_common()),
              'slotted_weighted': dict(slots)}
    print(h[:12], nfile, dict(wtd.most_common(12)), flush=True)
json.dump(out, open(sys.argv[2], 'w'), indent=1)
