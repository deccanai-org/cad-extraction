#!/usr/bin/env python3
"""BOX probe (coverage-regression): does each model's OWN profdb.bin define the profiles its parts miss (washers, studs,
TJI/LVL, KSP joists, BAR...)? For every model zip: verify the .db1 sha256, read the sibling profdb.bin, and for each missed name
report the name-table entry (family / type code) and the parameter block (index record or order between anchors).
usage: probe_profdb.py ZIPS_JSON WANT_JSON OUT_JSON      ZIPS_JSON: [{"zip_key", "label"}]
"""
import os, sys, json, io, zipfile, hashlib, struct, collections
import boto3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profdb
B = 'bim-proprietary-data'
s3 = boto3.client('s3', region_name='ap-south-1')
zips, want, outp = json.load(open(sys.argv[1])), json.load(open(sys.argv[2])), sys.argv[3]
out = {}
for zj in zips:
    raw = s3.get_object(Bucket=B, Key=zj['zip_key'])['Body'].read()
    z = zipfile.ZipFile(io.BytesIO(raw))
    names = z.namelist()
    for m in [n for n in names if n.lower().endswith('.db1') and not n.lower().endswith('xslib.db1')]:
        sha = hashlib.sha256(z.read(m)).hexdigest()
        if sha not in want:
            continue
        folder = m.rsplit('/', 1)[0] + '/' if '/' in m else ''
        pk = next((n for n in names if n.lower() == (folder + 'profdb.bin').lower()), None)
        rec = {'zip_key': zj['zip_key'], 'member': m, 'profdb': pk, 'want': want[sha]}
        if pk:
            d = profdb.load_bytes(z.read(pk)) if hasattr(profdb, 'load_bytes') else z.read(pk)
            if d[:2] == b'\x1f\x8b':
                import gzip; d = gzip.decompress(d)
            nm, vals = profdb.parse(d)
            byname = {}
            for p_, n_ in nm.items():
                byname.setdefault(n_, p_)
            tab = {n: (fam, code) for o, n, fam, code in profdb.table_entries(d)}
            fm = profdb.full_map(d)
            rec['profdb_names'] = len(nm); rec['table_entries'] = len(tab)
            rec['families'] = dict(collections.Counter(f'{f}/{c}' for f, c in tab.values()).most_common(30))
            res = {}
            for w in want[sha]:
                e = {'in_table': w in tab, 'family_type': tab.get(w), 'index_pid': byname.get(w)}
                if w in fm:
                    e['how'] = fm[w]['how']; e['params'] = fm[w]['vals']
                elif byname.get(w) in vals:
                    e['how'] = 'index'; e['params'] = vals[byname[w]]
                # near names (trailing blanks, case)
                if not e['in_table']:
                    e['near'] = [n for n in tab if n.strip().lower() == w.strip().lower()][:3]
                res[w] = e
            rec['resolved'] = res
        out[sha] = rec
        print(zj.get('label'), sha[:12], 'profdb', bool(pk), json.dumps({k: (v.get('family_type'), v.get('how'), v.get('params')) for k, v in (rec.get('resolved') or {}).items()}, default=str)[:900], flush=True)
json.dump(out, open(outp, 'w'), indent=1, default=str)
print('DONE', len(out))
