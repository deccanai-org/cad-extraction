"""harness2.py KITDIR DB1 OUTJSON
Runs the kit's own db1step.convert on one DB1 exactly as convert_one.py does (base catalog + per-model overlay + DB1_SHA256 for the
per-model bolt catalog), with read-only probes (the IFC is not written; everything else is the unmodified kit code path):
  * every bolt returned by db1bolts.bolts_of() is tagged with its group's string / material (extra keys, unused by the kit)
  * every db1bolts.hole_diameter() call (one per hole cut) is logged
Output: the kit's bolt_stats + per-hole cause under the DEPLOYED rule (code i: tolerance used only when 0 < t <= 10) +
per-string table + census of every bolt-group record (obj_type 10) of the model."""
import sys, os, json, collections, hashlib, time, re, gzip
KIT, DB1, OUT = sys.argv[1:4]
DB1 = os.path.abspath(DB1); OUT = os.path.abspath(OUT)
sys.path.insert(0, os.path.abspath(KIT))
os.chdir(os.path.abspath(KIT))
SHA = hashlib.sha256(open(DB1, 'rb').read()).hexdigest()
os.environ['DB1_SHA256'] = SHA
import db1bolts, db1step

cat = json.load(open('tekla_profiles.json'))
ovp = 'tekla_profiles_overlay.json'
if os.path.exists(ovp):
    ov = json.load(open(ovp))
    for src in (ov.get('global') or {}, (ov.get('per_model') or {}).get(SHA) or {}):
        cat.update({k: {'kind': v['kind'], 'dims': v['dims'], 'overlay': v.get('src')} for k, v in src.items()})


def fields(prof):
    return (prof or '').split('/')


def deployed_cause(prof):
    """why code i's bolt_tolerance() returns None for this string (or 'decoded')"""
    p = fields(prof)
    if len(p) < 4:
        return 'no_field4'
    try:
        t = float(p[3])
    except ValueError:
        return 'field4_not_numeric'
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
    LOG.append((bool(dec), round(float(dh), 3), b.get('_prof'), b.get('_mat'), bool(b.get('holes_only')), float(b.get('d_stored', b['d'])),
                b.get('tol'), b.get('tol_status')))
    return dh, dec


db1bolts.hole_diameter = hole_diameter
db1step.IfcOut.write = lambda self, path: None

t0 = time.time()
st = db1step.convert(DB1, '/dev/null', cat, None, [], allow_full=False)
st.pop('parts_list', None)
res = {'db1': os.path.basename(DB1), 'sha256': SHA, 'kit': os.path.basename(os.path.abspath(KIT)), 'status': st.get('status'),
       'secs': round(time.time() - t0, 1), 'bolt_stats': st.get('bolt_stats'), 'members': st.get('members')}
by_cause = collections.Counter(); per_str = {}; diam = collections.Counter()
for dec, dh, prof, mat, ho, d, tol, tst in LOG:
    c = deployed_cause(prof)
    by_cause[c] += 1
    k = f'{prof} | {mat}'
    e = per_str.setdefault(k, {'prof': prof, 'mat': mat, 'holes_only': ho, 'd_stored': d, 'cause_deployed_rule': c, 'holes': 0,
                               'holes_decoded_by_kit': 0, 'hole_d': collections.Counter(), 'tol_status': collections.Counter()})
    e['holes'] += 1; e['holes_decoded_by_kit'] += 1 if dec else 0; e['hole_d'][f'{dh:g}'] += 1; e['tol_status'][str(tst)] += 1
    diam[f'{dh:g}'] += 1
res['holes_total'] = len(LOG)
res['holes_by_cause_deployed_rule'] = dict(by_cause)
res['holes_decoded_by_kit'] = sum(1 for x in LOG if x[0])
res['holes_nominal_by_kit'] = sum(1 for x in LOG if not x[0])
res['hole_diameters'] = dict(diam)
res['strings'] = sorted(({**v, 'hole_d': dict(v['hole_d']), 'tol_status': dict(v['tol_status'])} for v in per_str.values()),
                        key=lambda v: -v['holes'])
# census of the model's bolt-group records
import db1old
data = open(DB1, 'rb').read()
if data[:2] == b'\x1f\x8b':
    data = gzip.decompress(data)
eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
res['engine'] = eng
if eng < 7.5:
    M, info, _ = db1old.read(data, eng)
    g = collections.Counter(); nf = collections.Counter(); f4 = collections.Counter(); slot = collections.Counter(); ln = collections.Counter()
    for m in M:
        if not m.get('bolt'):
            continue
        p = fields(m.get('prof'))
        c = deployed_cause(m.get('prof'))
        g[c] += 1; nf[len(p)] += 1; ln[len(m.get('prof') or '')] += 1
        if len(p) >= 4:
            ho = '?'
            try:
                ho = ('%06d' % int(float(p[8])))[0] == '1'
            except Exception:
                pass
            f4[f'{p[3]} holes_only={ho} cut={bool(m.get("cut"))}'] += 1
        try:
            if float(p[1]) != 0 or float(p[2]) != 0:
                slot['groups_with_slot_fields'] += 1
        except Exception:
            pass
    res['bolt_group_records_by_cause'] = dict(g)
    res['bolt_string_field_counts'] = dict(nf)
    res['bolt_string_lengths'] = dict(ln)
    res['field4_values'] = dict(f4.most_common())
    res['slots'] = dict(slot)
    res['old_info'] = info
json.dump(res, open(OUT, 'w'), indent=1, default=str)
print(json.dumps({k: res.get(k) for k in ('db1', 'kit', 'status', 'secs', 'holes_total', 'holes_by_cause_deployed_rule', 'holes_nominal_by_kit')},
                 default=str), flush=True)
