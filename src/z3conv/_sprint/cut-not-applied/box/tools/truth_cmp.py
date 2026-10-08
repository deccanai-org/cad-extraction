"""truth_cmp.py NAME : per-part comparison with Tekla's own IFC export of the same model (QuantityTakeOff NetVolume per part).
DB1 part id -> Tekla GUID (DB1 object records 'ID<guid>') -> IFC GlobalId -> NetVolume; our volumes from the pipeline runs
pipes2/{kit2,kitp2,nc}/truth_NAME (STEP read-back, joined by our GlobalId through the decoder parts list)."""
import sys, os, re, json, gzip, collections, numpy as np
W = '/work/agentwork/cut-not-applied'; NAME = sys.argv[1]
sys.path.insert(0, W + '/kitp2')
import db1old, db1prof
from db1dec import load
import ifcopenshell, ifcopenshell.guid
data = load(f'{W}/truth/{NAME}.db1'); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
M, info, cut_rel = db1old.read(data, eng)
byp = {m['pid']: m for m in M}
# --- DB1 object id -> GUID (Tekla object records hold the GUID string; the object id sits at a fixed offset before it, found per file
#     as the offset whose ints hit decoded part ids most often among the GUIDs present in the Tekla IFC)
import ifcopenshell as _ios, ifcopenshell.guid as _iog
_f0 = _ios.open(f'{W}/truth/{NAME}.ifc')
_ifc_g = {_iog.expand(e.GlobalId).upper().replace('-', '') for e in _f0.by_type('IfcElement')}
RX = re.compile(rb'([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})')
G = [(m.start(), m.group(1).decode().upper().replace('-', '')) for m in RX.finditer(data)]
keys = np.array(sorted(byp), np.int64); u8 = np.frombuffer(data, np.uint8)
GI = [(p, g) for p, g in G if g in _ifc_g] or G
pos = np.array([p for p, _ in GI], np.int64)
best = None
for k in range(2, 80):
    p = pos - k; ok = p >= 0
    v = np.zeros(len(p), np.int64); v[ok] = u8[p[ok][:, None] + np.arange(4)].copy().view('<i4')[:, 0]
    i = np.searchsorted(keys, v); i[i >= len(keys)] = 0; n = int((keys[i] == v).sum())
    if best is None or n > best[1]: best = (k, n)
k = best[0]; pid2guid = {}
for g, s_ in G:
    v = int.from_bytes(data[g - k:g - k + 4], 'little', signed=True)
    if v in byp: pid2guid.setdefault(v, s_)
# --- Tekla IFC: GlobalId -> (class, name, profile, NetVolume)
f = ifcopenshell.open(f'{W}/truth/{NAME}.ifc')
tek = {}
for e in f.by_type('IfcElement'):
    if e.is_a('IfcOpeningElement'): continue
    q = {}
    for r in getattr(e, 'IsDefinedBy', []) or []:
        if not r.is_a('IfcRelDefinesByProperties'): continue
        pd = r.RelatingPropertyDefinition
        if pd.is_a('IfcElementQuantity'):
            for x in pd.Quantities:
                if x.is_a('IfcQuantityVolume'): q[x.Name] = x.VolumeValue
                elif x.is_a('IfcQuantityWeight'): q[x.Name] = x.WeightValue
                elif x.is_a('IfcQuantityLength'): q[x.Name] = x.LengthValue
        elif pd.is_a('IfcPropertySet') and pd.Name in ('BaseQuantities', 'Pset_Tekla_General'):
            for x in pd.HasProperties:
                v = getattr(x, 'NominalValue', None)
                if v is not None and isinstance(v.wrappedValue, (int, float)): q.setdefault(x.Name, float(v.wrappedValue))
    rt = None
    try:
        rt = '|'.join(sorted({r.RepresentationType for r in e.Representation.Representations if r.RepresentationIdentifier == 'Body'}))
    except Exception: pass
    q['_rep'] = rt
    tek[ifcopenshell.guid.expand(e.GlobalId).upper().replace('-', '')] = (e.is_a(), e.Name, getattr(e, 'ObjectType', None), q)
# volume unit of the IFC (m3 or mm3)
def runv(v):
    d = f'{W}/pipes2/{v}/truth_{NAME}'
    pl = os.path.join(d, 'convert.json.parts.json.gz'); sp = os.path.join(d, 'step_parts.jsonl.gz')
    if not (os.path.exists(pl) and os.path.exists(sp)): return None
    vol = collections.Counter()
    for l in gzip.open(sp, 'rt'):
        s = json.loads(l)
        if s.get('pid') and s.get('volume') is not None: vol[s['pid']] += s['volume']
    out = {}
    for pid, prof, cat, st, how, gid, nc in json.load(gzip.open(pl, 'rt')):
        out[pid] = (st, how, nc, vol.get(gid) if gid else None)
    return out
R = {v: runv(v) for v in ('kit2', 'kitp2', 'nc')}
print('==', NAME, eng, 'parts', len(M), 'guid offset', best, 'pids with guid', len(pid2guid), 'tekla elements', len(tek),
      'with NetVolume', sum(1 for t in tek.values() if 'NetVolume' in t[3]), 'runs', {v: (len(r) if r else None) for v, r in R.items()})
nv = [t[3]['NetVolume'] for t in tek.values() if 'NetVolume' in t[3]]
scale = 1e9 if nv and np.median(nv) < 10 else 1.0          # m3 -> mm3
print('   NetVolume median', np.median(nv) if nv else None, 'scale', scale)
# --- classification
st = collections.Counter(); rows = []; GROSS = {}; REP = {}
for m in M:
    pid = m['pid']; g = pid2guid.get(pid); t = tek.get(g) if g else None
    kind = 'cut' if m['cut'] else ('bolt' if m['bolt'] else 'part')
    st[(kind, 'in_tekla_ifc' if t else 'not_in_ifc')] += 1
    if m['cut'] and not m['mat'] == 'ANTIMATERIAL':
        st[('operative_part(obj_type11)', 'in_tekla_ifc' if t else 'not_in_ifc')] += 1
    if kind != 'part' or not t or 'NetVolume' not in t[3]: continue
    tn = t[3]['NetVolume'] * scale
    vals = {v: (R[v].get(pid) if R[v] else None) for v in R}
    rows.append((pid, m['prof'], tn, vals))
    if 'GrossVolume' in t[3]: GROSS[pid] = t[3]['GrossVolume'] * scale
    REP[pid] = t[3].get('_rep')
print('   decoded vs Tekla IFC:', sorted(st.items()))
# --- per-part volume agreement
def agree(v, tol):
    n = ok = 0
    for pid, prof, tn, vals in rows:
        x = vals.get(v)
        if not x or x[0] != 'written' or not x[3]: continue
        n += 1; ok += abs(x[3] - tn) <= tol * tn
    return ok, n
for tol in (0.005, 0.01, 0.02):
    print('   parts within %.1f%% of Tekla NetVolume:' % (100 * tol), {v: agree(v, tol) for v in R if R[v]})
# parts Tekla shows cut (net < our gross by > 1%): before / after
cutp = [(pid, prof, tn, vals) for pid, prof, tn, vals in rows if vals.get('nc') and vals['nc'][3] and tn < vals['nc'][3] * 0.99]
def ok1(x, tn): return x and x[0] == 'written' and x[3] and abs(x[3] - tn) <= 0.01 * tn
print('   parts with Tekla net < our gross by >1%%: %d | within 1%% of Tekla net: kit2 %d, kitp2 %d' % (len(cutp), sum(1 for r in cutp if ok1(r[3].get('kit2'), r[2])), sum(1 for r in cutp if ok1(r[3].get('kitp2'), r[2]))))
over = [(pid, prof, tn, vals) for pid, prof, tn, vals in rows if vals.get('kitp2') and vals['kitp2'][3] and vals['kitp2'][3] < tn * 0.99]
print('   parts where kitp2 is >1%% below Tekla net (over-cut or wrong section): %d; kit2: %d' % (len(over), sum(1 for pid, prof, tn, vals in rows if vals.get('kit2') and vals['kit2'][3] and vals['kit2'][3] < tn * 0.99)))
for r in cutp[:8] + over[:8]:
    pid, prof, tn, vals = r
    print('      ', pid, prof, 'tekla net %.0f' % tn, {v: (round(x[3]) if x and x[3] else None, x[2] if x else None) for v, x in vals.items()})

# gross sanity: our uncut volume (nc) vs Tekla GrossVolume (section + length agreement, independent of cuts)
gs = [(pid, GROSS[pid], vals['nc'][3]) for pid, prof, tn, vals in rows if pid in GROSS and vals.get('nc') and vals['nc'][3]]
if gs:
    r = np.array([b / a for _, a, b in gs])
    print('   our gross / Tekla GrossVolume: n %d median %.4f p5 %.4f p95 %.4f within 1%%: %d' % (len(r), np.median(r), np.percentile(r, 5), np.percentile(r, 95), int((abs(r - 1) <= 0.01).sum())))
# cut removal agreement: Tekla (gross - net) vs ours (nc - after), parts where either removes > 0.5% of gross
rem = []
for pid, prof, tn, vals in rows:
    if pid not in GROSS or not vals.get('nc') or not vals['nc'][3]: continue
    tg = GROSS[pid]; tr = tg - tn
    for v in ('kit2', 'kitp2'):
        x = vals.get(v)
        if not x or not x[3]: continue
    a = vals.get('kit2'); b = vals.get('kitp2'); g = vals['nc'][3]
    if not (a and a[3] and b and b[3]): continue
    ra, rb = g - a[3], g - b[3]
    if max(tr, ra, rb) > 0.005 * tg:
        rem.append((pid, prof, tr, ra, rb, tg))
def close(x, y, tg): return abs(x - y) <= max(0.1 * abs(y), 0.002 * tg)
print('   parts where Tekla or we remove >0.5%% of gross: %d | removal within 10%% of Tekla: kit2 %d  kitp2 %d | Tekla removes, we do not: kit2 %d kitp2 %d | we remove, Tekla does not: kit2 %d kitp2 %d' % (
    len(rem), sum(close(ra, tr, tg) for _, _, tr, ra, rb, tg in rem), sum(close(rb, tr, tg) for _, _, tr, ra, rb, tg in rem),
    sum(1 for _, _, tr, ra, rb, tg in rem if tr > 0.005 * tg and ra <= 0.001 * tg), sum(1 for _, _, tr, ra, rb, tg in rem if tr > 0.005 * tg and rb <= 0.001 * tg),
    sum(1 for _, _, tr, ra, rb, tg in rem if tr <= 0.001 * tg and ra > 0.005 * tg), sum(1 for _, _, tr, ra, rb, tg in rem if tr <= 0.001 * tg and rb > 0.005 * tg)))
for r in rem[:12]: print('      pid %s %s tekla removes %.0f | kit2 %.0f kitp2 %.0f mm3 (gross %.0f)' % r)

# Tekla exports a part without cuts as a plain extrusion (SweptSolid) and a cut part as a B-rep: per profile, the section factor
# f = Tekla NetVolume / our uncut volume on the SweptSolid parts (profile modelling + catalog area); for the B-rep (cut) parts the
# prediction f x our volume is compared with Tekla's NetVolume, deployed kit vs patched kit.
fs = collections.defaultdict(list)
for pid, prof, tn, vals in rows:
    x = vals.get('nc')
    if REP.get(pid) == 'SweptSolid' and x and x[3]: fs[prof].append(tn / x[3])
fp = {p: float(np.median(v)) for p, v in fs.items() if len(v) >= 2 and np.std(v) < 0.01}
print('   B-rep (cut in Tekla) vs SweptSolid parts:', collections.Counter(REP.get(r[0]) for r in rows).most_common(4), '| profiles with a stable section factor', len(fp))
ev = collections.Counter(); bad = []
for pid, prof, tn, vals in rows:
    if REP.get(pid) in (None, 'SweptSolid') or prof not in fp: continue
    ev['brep_parts_with_factor'] += 1
    for v in ('kit2', 'kitp2', 'nc'):
        x = vals.get(v)
        if not x or not x[3]: continue
        e = abs(fp[prof] * x[3] - tn) / tn
        ev[v + '_within1%'] += e <= 0.01; ev[v + '_within2%'] += e <= 0.02; ev[v + '_within5%'] += e <= 0.05
    a, b = vals.get('kit2'), vals.get('kitp2')
    if a and b and a[3] and b[3] and abs(fp[prof] * b[3] - tn) > abs(fp[prof] * a[3] - tn) + 0.005 * tn: bad.append((pid, prof, round(tn), round(fp[prof] * a[3]), round(fp[prof] * b[3]), a[2], b[2]))
print('   Tekla-cut parts, f x our volume vs Tekla NetVolume:', dict(ev))
print('   patched worse than deployed by >0.5%%: %d e.g. %s' % (len(bad), bad[:6]))
# flat-faced parts (plates / flats / bars: no fillets, no facetted curves): our volume vs Tekla NetVolume directly
import re as _re
PLT = _re.compile(r'^(PL|PLT|FL|FLT|BL|PLATE|BAR)\s*\d')
ev = collections.Counter(); ex = []
for pid, prof, tn, vals in rows:
    if not prof or not PLT.match(prof.upper()): continue
    a, b, g = vals.get('kit2'), vals.get('kitp2'), vals.get('nc')
    if not (a and b and g and a[3] and b[3] and g[3]): continue
    ev['plates'] += 1
    cutp = g[3] - b[3] > 0.005 * g[3]                     # the patch cuts material from it
    tcut = tn < g[3] * 0.995                              # Tekla's solid is smaller than ours uncut
    ev['tekla_smaller_than_our_uncut'] += tcut
    for v, x in (('kit2', a), ('kitp2', b)):
        e = abs(x[3] - tn) / tn
        ev[v + '_within1%'] += e <= 0.01
        if cutp: ev[v + '_within1%_on_patch_cut_plates'] += e <= 0.01
    ev['patch_cut_plates'] += cutp
    if cutp and len(ex) < 8: ex.append((pid, prof, round(tn), round(g[3]), round(a[3]), round(b[3]), a[2], b[2]))
print('   flat plates vs Tekla NetVolume:', dict(ev))
for e in ex: print('      pid %s %s tekla %d | uncut %d kit2 %d kitp2 %d (cuts %s -> %s)' % e)
# same model revision? our reference length L vs Tekla 'Length' (BaseQuantities)
lc = collections.Counter(); lex = collections.defaultdict(list)
for m in M:
    if m['cut'] or m['bolt']: continue
    t = tek.get(pid2guid.get(m['pid']))
    if not t or 'Length' not in t[3]: continue
    d = m['L'] - t[3]['Length']; k = 'same' if abs(d) <= 1 else ('ours_longer' if d > 0 else 'ours_shorter')
    lc[k] += 1
    if len(lex[k]) < 4: lex[k].append((m['prof'], round(m['L'], 1), round(t[3]['Length'], 1)))
print('   reference length vs Tekla Length:', dict(lc), dict(lex))
