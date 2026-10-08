"""truth_cmp2.py NAME label=pipedir ... (generalised truth_cmp.py; KIT env = kit whose db1old decodes the fittings) : per-part comparison with Tekla's own IFC export of the same model (QuantityTakeOff NetVolume per part).
DB1 part id -> Tekla GUID (DB1 object records 'ID<guid>') -> IFC GlobalId -> NetVolume; our volumes from the pipeline runs
pipes2/{kit2,kitp2,nc}/truth_NAME (STEP read-back, joined by our GlobalId through the decoder parts list)."""
import sys, os, re, json, gzip, collections, numpy as np
W = '/work/agentwork/cut-not-applied'; NAME = sys.argv[1]
sys.path.insert(0, os.environ.get('KIT', W + '/kitnp4'))
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
    d = v
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

VAR = [a.split('=', 1) for a in sys.argv[2:]]
R = {lab: runv(d) for lab, d in VAR}
print('==', NAME, eng, 'parts', len(M), 'guid offset', best, 'pids with guid', len(pid2guid), 'tekla elements', len(tek),
      'with NetVolume', sum(1 for t in tek.values() if 'NetVolume' in t[3]), 'runs', {v: (len(r) if r else None) for v, r in R.items()})
nv = [t[3]['NetVolume'] for t in tek.values() if 'NetVolume' in t[3]]
scale = 1e9 if nv and np.median(nv) < 10 else 1.0
FITD = getattr(db1old, 'FIT', {}) or {}
fitted = set(FITD.get(9, {})) | set(FITD.get(12, {}))
print('   fittings decoded (db1old.FIT): type9 parts', len(FITD.get(9, {})), 'planes', sum(len(v) for v in FITD.get(9, {}).values()),
      '| type12 parts', len(FITD.get(12, {})), 'planes', sum(len(v) for v in FITD.get(12, {}).values()), '| info', info.get('fittings_decoded'))
rows = []
for m in M:
    pid = m['pid']; g = pid2guid.get(pid); t = tek.get(g) if g else None
    if m['cut'] or m['bolt'] or not t or 'NetVolume' not in t[3]: continue
    rows.append((pid, m['prof'], t[3]['NetVolume'] * scale, {v: (R[v].get(pid) if R[v] else None) for v in R}, t[3].get('Length'), m['L']))
def vol(x): return x[3] if x and x[0] == 'written' and x[3] else None
for subset, sel in (('all parts', lambda r: True), ('parts with fittings / line cuts', lambda r: r[0] in fitted), ('parts without', lambda r: r[0] not in fitted)):
    rr = [r for r in rows if sel(r)]
    out = {}
    for v in R:
        if not R[v]: continue
        e = [abs(vol(r[3][v]) - r[2]) / r[2] for r in rr if vol(r[3].get(v)) and r[2] > 0]
        out[v] = dict(n=len(e), within_0_5pct=sum(x <= 0.005 for x in e), within_1pct=sum(x <= 0.01 for x in e), within_2pct=sum(x <= 0.02 for x in e),
                      median_err_pct=round(100 * float(np.median(e)), 3) if e else None, sum_abs_err_m3=round(sum(abs(vol(r[3][v]) - r[2]) for r in rr if vol(r[3].get(v))) / 1e9, 4))
    print('   %-34s' % subset, len(rr), json.dumps(out))
labs = [lab for lab, _ in VAR if R[lab]]
for i in range(len(labs)):
    for j in range(i + 1, len(labs)):
        a, b = labs[i], labs[j]; ch = collections.Counter(); ex = collections.defaultdict(list)
        for r in rows:
            va, vb = vol(r[3].get(a)), vol(r[3].get(b))
            if not va or not vb: continue
            ea, eb = abs(va - r[2]) / r[2], abs(vb - r[2]) / r[2]
            k = 'improved' if eb < ea - 0.005 else ('worsened' if eb > ea + 0.005 else 'same')
            ch[k] += 1
            if k != 'same' and len(ex[k]) < 8: ex[k].append((r[0], r[1], 'tekla', round(r[2]), a, round(va), b, round(vb), 'TeklaL', r[4], 'L', round(r[5], 1)))
        print('   %s -> %s per part (>0.5%% of Tekla net):' % (a, b), dict(ch))
        for k in ('worsened', 'improved'):
            for e in ex[k]: print('      ', k, e)
