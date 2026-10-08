"""ncslot.py NC_FIND_JSON OUT_JSON : are the old-engine 'slot x / slot y' bolt-string fields real slotted holes? Evidence from Tekla's own
DSTV NC files next to each model (folder list from hole-tolerance-residue nc_find.json). DSTV BO line: plane x y diameter depth
[slot-length slot-width slot-angle]; a slotted hole has slot-length > 0 (token 5). Counts BO holes per (diameter, slotted?) weighted by
the ST quantity, plus the slot-length values seen."""
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
    bo = []; blk = None
    for l in L:
        s = l.strip()
        if re.fullmatch(r'[A-Z]{2}', s):
            blk = s; continue
        if not s or blk != 'BO': continue
        t = s.split()
        if t[0] in ('v', 'o', 'u', 'h') and len(t) >= 4:
            try:
                dd = num(t[3])
                sl = num(t[5]) if len(t) >= 6 else 0.0
                if dd > 0: bo.append((round(dd, 2), round(sl, 2)))
            except ValueError:
                pass
    return q, bo


def model(h, v):
    lv = next((x for k, x in v.items() if x.get('nc')), None)
    if not lv: return h, None
    ks = [k for d in lv['nc_dirs'] for k in keys_of(d + '/') if os.path.dirname(k) == d]
    c = collections.Counter(); sl = collections.Counter(); nf = 0; parts_sl = 0
    for k in ks:
        try:
            txt = s3.get_object(Bucket=B, Key=k)['Body'].read().decode('latin1')
        except Exception:
            continue
        nf += 1; q, bo = parse(txt)
        if any(x[1] > 0 for x in bo): parts_sl += 1
        for dd, s_ in bo:
            c[(dd, s_ > 0)] += q
            if s_ > 0: sl[s_] += q
    return h, {'nc_files': nf, 'parts_with_slotted_bo': parts_sl, 'bo_by_d_slotted': {f'{d}|{"slot" if s else "round"}': n for (d, s), n in c.most_common()},
               'slot_lengths': dict(sl.most_common(20)), 'dirs': lv['nc_dirs']}


with cf.ThreadPoolExecutor(8) as ex:
    for h, r in ex.map(lambda kv: model(*kv), R.items()):
        if r: out[h] = r
json.dump(out, open(sys.argv[2], 'w'), indent=1)
s3.upload_file(sys.argv[2], B, 'cad-disk-extract/zenitude-data-3/_state/agentwork/class1-readiness-audit/' + os.path.basename(sys.argv[2]))
print(len(out), 'models with NC files')
