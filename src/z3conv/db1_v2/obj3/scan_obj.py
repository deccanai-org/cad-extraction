"""data-3 DB1: obj_type distribution of the attribute records that part/member-like records point to (bolt groups = 10;
look for other bolt-like types, e.g. 3) + whether such records carry a bolt string or bolt attribute fields. scan_obj.py JOBS OUT"""
import sys, os, json, re, collections, numpy as np, zlib, gzip, boto3, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
s3 = boto3.client('s3', region_name='ap-south-1')
jobs = json.load(open(sys.argv[1])); out = open(sys.argv[2], 'w')
for j in jobs:
    row = {'sha': j['sha256'][:12]}
    try:
        p = '/tmp/scanobj.db1'; s3.download_file('bim-proprietary-data', j['input_key'], p)
        raw = open(p, 'rb').read(); d = gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw
        eng = re.search(rb'(\d+\.\d+)', d[:16]).group(1).decode(); row['engine'] = eng
        if float(eng) < 7.5:
            import db1old
            M, info, cut = db1old.read(d, float(eng))
            o = db1old.Old(d); I = o.I_all; N = len(I) - 400
            av = np.zeros(N, bool); Mx = N - 380
            av[:Mx] = (I[:Mx] > 0) & (I[4:Mx + 4] >= 0) & (I[4:Mx + 4] <= 100) & (I[72:Mx + 72] >= 0) & (I[72:Mx + 72] <= 64)
            pr = o.u8[124:124 + Mx]; av[:Mx] &= (pr >= 32) & (pr <= 126)
            A = {}
            for q in o.runs(av, 373):
                if o.u8[int(q) - 1] == 4 or int(I[q]) not in A: A[int(I[q])] = (int(I[q + 4]), o.cstr(int(q) + 124, 62))
            c = collections.Counter(); ex = {}
            for m in M:
                t, prf = A.get(m.get('attr'), (None, None))
                c[str(t)] += 1
                ex.setdefault(str(t), [])
                if len(ex[str(t)]) < 5 and prf not in ex[str(t)]: ex[str(t)].append(prf)
            row['attr_obj_types'] = dict(c); row['examples'] = ex
        else:
            from db1dec import decode, members, Db
            L = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'layouts.json')))
            VA = [v['layout'] for v in L.values() if v.get('layout')]
            db, pts, cs, lay = decode(d, (L.get(eng) or {}).get('layout'), VA, len(d) < 20_000_000)
            c = collections.Counter(); ex = {}
            for st_, recs in db.runs:
                if st_ < 33: continue
                a = db.I(recs + 13); ao = db.lookup(a); ok = ao >= 0
                ob = np.where(ok, db.I(np.where(ok, ao, 0) + 13), -999)
                S = db.lookup_stride(a)
                for t, s2, aa in zip(ob[ok], S[ok], ao[ok]):
                    k = (int(st_) % 65 == 0 and 'm65') or (int(st_) % 73 == 0 and 'm73') or (int(st_) % 33 == 0 and 'h33') or 'other'
                    if k == 'other': continue
                    c[(k, int(t), int(s2))] += 1
                    if (k, int(t), int(s2)) not in ex:
                        ex[(k, int(t), int(s2))] = [m.group().decode('latin1') for m in re.finditer(rb'[\x20-\x7e]{4,}', db.b[int(aa):int(aa) + int(s2)])][:4]
            row['ref_obj_types'] = {str(k): v for k, v in c.most_common(12)}
            row['examples'] = {str(k): ex[k] for k, v in c.most_common(12)}
    except Exception as e:
        row['error'] = traceback.format_exc()[-300:]
    out.write(json.dumps(row) + '\n'); out.flush(); print(row.get('sha'), row.get('engine'), row.get('attr_obj_types') or row.get('ref_obj_types'), flush=True)
