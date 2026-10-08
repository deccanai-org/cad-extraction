"""Light decode of an old-engine Tekla DB1 (no IFC, no geometry): per-bolt records exactly as db1step.convert_old builds them
(db1old.read -> null-record + axis-guard filter -> db1bolts.bolts_of) + per-part section source (section_for with the kit catalog
+ overlay as convert_one merges it). usage: light_decode.py KIT DB1 OUT_JSON"""
import sys, os, json, hashlib, re, collections, time
KIT = os.path.abspath(sys.argv[1]); sys.path.insert(0, KIT)
import numpy as np
db1, outp = sys.argv[2], sys.argv[3]
t0 = time.time()
cat = json.load(open(os.path.join(KIT, 'tekla_profiles.json')))
ov = json.load(open(os.path.join(KIT, 'tekla_profiles_overlay.json')))
h = hashlib.sha256(open(db1, 'rb').read()).hexdigest()
for src in (ov.get('global') or {}, (ov.get('per_model') or {}).get(h) or {}):
    cat.update({k: {'kind': v['kind'], 'dims': v['dims'], 'overlay': v.get('src')} for k, v in src.items()})
import db1old, db1prof, db1bolts
from db1step import section_for
data = open(db1, 'rb').read()
if data[:2] == b'\x1f\x8b':
    import gzip, zlib
    try: data = gzip.decompress(data)
    except EOFError: data = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(data)
ban = re.search(rb'(\d+\.\d+)', data[:16]); engine = float(ban.group(1)) if ban else 0.0
out = {'sha256': h, 'engine': '%.2f' % engine}
if not (0 < engine < 7.5):
    out['status'] = 'new_engine_not_light_decoded'; json.dump(out, open(outp, 'w')); sys.exit(0)
M, info, cut_rel = db1old.read(data, engine)
nul = [m for m in M if db1prof.is_null_record(m)]
M = [m for m in M if not db1prof.is_null_record(m)]
bad_axis = sum(1 for m in M if m.get('axis_ok') is False)
M = [m for m in M if m.get('axis_ok') is not False]
bolts = []; parts = []
for m in M:
    if m.get('cut'):
        continue
    if m.get('bolt'):
        bl = db1bolts.bolts_of(m)
        if bl:
            for b in bl:
                sg = b.get('std')
                bolts.append({'pid': m.get('pid'), 'prof': m.get('prof'), 'mat': m.get('mat'), 'd': b['d'], 'd_stored': b['d_stored'], 'L': b['L'],
                              'std_family': sg['family'] if sg else None, 'std_mapping': sg['mapping'] if sg else None, 'tol': b.get('tol'),
                              'holes_only': b.get('holes_only'), 'wash_head': b.get('wash_head'), 'wash_nut': b.get('wash_nut'), 'nuts': b.get('nuts'),
                              'axial_decoded': b.get('axial_decoded')})
            continue
    kind, v, how = section_for(m.get('prof'), cat)
    parts.append([m.get('pid'), m.get('prof'), kind, how if kind else v, (cat.get(m.get('prof')) or {}).get('overlay')])
out.update(status='ok', members=len(M), null_records=len(nul), axis_dropped=bad_axis, bolts=bolts, parts=parts, sec=round(time.time() - t0, 1))
json.dump(out, open(outp, 'w'), default=str)
