"""harness.py KITDIR DB1 OUTJSON
Runs the kit's own db1step.convert on one DB1 exactly as convert_one.py does (base catalog + overlay), with two read-only probes:
  * every bolt returned by db1bolts.bolts_of() is tagged with its group's profile string / material (extra keys, unused by the kit)
  * every call of db1bolts.hole_diameter() (one per hole cut) is logged with the cause of a nominal diameter
The IFC is not written (IfcOut.write is a no-op); everything else is the unmodified kit code path.
Output: bolt_stats of the kit + per-cause hole counts + census of the bolt-group records of the model."""
import sys, os, json, collections, hashlib, time
KIT, DB1, OUT = sys.argv[1:4]
DB1 = os.path.abspath(DB1); OUT = os.path.abspath(OUT)
sys.path.insert(0, os.path.abspath(KIT))
os.chdir(os.path.abspath(KIT))
import numpy as np
os.environ['DB1_SHA256'] = hashlib.sha256(open(DB1, 'rb').read()).hexdigest()   # as convert_one.py (code i: per-model bolt catalog)
import db1bolts, db1step

cat = json.load(open('tekla_profiles.json'))
ovp = 'tekla_profiles_overlay.json'
if os.path.exists(ovp):
    ov = json.load(open(ovp))
    h = hashlib.sha256(open(DB1, 'rb').read()).hexdigest()
    for src in (ov.get('global') or {}, (ov.get('per_model') or {}).get(h) or {}):
        cat.update({k: {'kind': v['kind'], 'dims': v['dims'], 'overlay': v.get('src')} for k, v in src.items()})


def kit_cause(prof):
    """why the KIT's bolt_tolerance() returns None for this string (or 'decoded')"""
    p = (prof or '').split('/')
    if len(p) < 4:
        return 'no_field4'
    try:
        t = float(p[3])
    except ValueError:
        return 'parse_fail'
    if t == 0:
        return 'tol_zero'
    if t < 0:
        return 'tol_negative'
    if t > 10:
        return 'tol_gt10'
    return 'decoded'


_bolts_of = db1bolts.bolts_of


def bolts_of(m):
    out = _bolts_of(m)
    for b in out:
        b.setdefault('_prof', m.get('prof')); b.setdefault('_mat', m.get('mat'))
    return out


db1bolts.bolts_of = bolts_of
LOG = []
_hd = db1bolts.hole_diameter


def hole_diameter(b):
    dh, dec = _hd(b)
    LOG.append((dec, round(float(dh), 3), b.get('_prof'), b.get('_mat'), b.get('pid'), bool(b.get('holes_only'))))
    return dh, dec


db1bolts.hole_diameter = hole_diameter
db1step.IfcOut.write = lambda self, path: None

t0 = time.time()
lay = None
st = db1step.convert(DB1, '/dev/null', cat, lay, [], allow_full=False)
pl = st.pop('parts_list', None)
res = {'db1': os.path.basename(DB1), 'status': st.get('status'), 'secs': round(time.time() - t0, 1), 'bolt_stats': st.get('bolt_stats'),
       'members': st.get('members')}
# per-hole causes
by_cause = collections.Counter(); by_string = collections.Counter(); diam = collections.Counter()
for dec, dh, prof, mat, pid, ho in LOG:
    c = 'decoded' if dec else kit_cause(prof)
    by_cause[c] += 1
    if not dec:
        by_string[f'{prof} | {mat} | holes_only={ho}'] += 1
    diam[f'{"dec" if dec else "nom"} {dh:g}'] += 1
res['holes_by_cause'] = dict(by_cause)
res['nominal_holes_by_string'] = by_string.most_common()
res['hole_diameters'] = dict(diam)
# census of the model's bolt-group records (obj_type 10) and MM-strings on other records
import db1old
data = open(DB1, 'rb').read()
if data[:2] == b'\x1f\x8b':
    import gzip
    data = gzip.decompress(data)
import re
eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
res['engine'] = eng
if eng < 7.5:
    M, info, _ = db1old.read(data, eng)
    g = collections.Counter(); other = collections.Counter()
    for m in M:
        if m.get('bolt'):
            g[f"{m.get('prof')} | {m.get('mat')} | cause={kit_cause(m.get('prof'))}"] += 1
        elif (m.get('prof') or '').startswith('MM'):
            other[m.get('prof')] += 1
    res['bolt_group_records'] = g.most_common()
    res['mm_strings_on_non_bolt_records'] = other.most_common(20)
json.dump(res, open(OUT, 'w'), indent=1, default=str)
print(json.dumps({k: res[k] for k in ('db1', 'status', 'secs', 'holes_by_cause')}, default=str))
