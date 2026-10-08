"""vnc.py KIT DB1 NCDIR[,..] OUT.json : slotted bolt groups (new + old engines) vs Tekla NC1 truth, per bolted part.
pred = decoder's slotted / not slotted (None = not decided); truth = NC hole at the group's bolt stations ('slot' with the stored length,
'round', 'other_slot'); direction: predicted slot long axis vs the part x axis (|cos|) and the NC slot angle."""
import sys, os, json, re, math, hashlib, collections, numpy as np
KIT = sys.argv[1]; sys.path.insert(0, KIT); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ALL = '6.87,7.01,7.24,7.30,7.64,7.82,7.89,7.98,8.07,8.44,8.53,8.62,8.65,8.85,8.95,9.08,9.21,9.50'
os.environ.setdefault('DB1_SLOT_ENGINES', ALL); os.environ.setdefault('DB1_V2_SLOT_ENGINES', ALL)
import db1step, ncparse
p, ncdirs, outp = sys.argv[2], sys.argv[3].split(','), sys.argv[4]
os.environ['DB1_SHA256'] = hashlib.sha256(open(p, 'rb').read()).hexdigest()
cat = json.load(open(os.path.join(KIT, 'tekla_profiles.json')))
tmp = '/tmp/_vnc_%d.ifc' % os.getpid()
import zlib as _z
_raw = open(p, 'rb').read(1 << 16)
_dat = _z.decompressobj(16 + _z.MAX_WBITS).decompress(_raw) if _raw[:2] == b'\x1f\x8b' else _raw
_eng = re.search(rb'(\d+\.\d+)', _dat[:16]).group(1).decode()
_LAY = json.load(open(os.path.join(KIT, 'layouts.json')))
st = db1step.convert(p, tmp, cat, (_LAY.get(_eng) or {}).get('layout'), [v_['layout'] for v_ in _LAY.values() if v_.get('layout')], False)
try: os.remove(tmp)
except OSError: pass
NC = []
for d in ncdirs:
    if os.path.isdir(d): NC += ncparse.load_dir(d)
PLATE = {'PL', 'BL', 'FL', 'FB', 'PLT', 'FLT', 'PLATE', 'BPL', 'FPL', 'FLAT', 'F.B', 'B', 'FLB'}
def fam(s):
    f = re.match(r'[A-Za-z\[\.]*', (s or '').strip()).group(0).upper()
    return 'PL' if f in PLATE else f
ncby = collections.defaultdict(list)
for r in NC: ncby[fam(r['prof'])].append(r)
hc = lambda h: h['x'] + (h['sl'] / 2) * math.cos(math.radians(h['sa'])) - (h['sw'] / 2) * math.sin(math.radians(h['sa']))
isl = lambda h: h['sl'] > 0 or h['sw'] > 0
def nc_along(h):     # NC slot long axis along the NC x axis? (True / False / None)
    a = h['sa'] if h['sl'] >= h['sw'] else h['sa'] + 90.0
    c = abs(math.cos(math.radians(a)))
    return True if c > 0.99 else (False if c < 0.01 else None)
def nc_label(O, x, L, prof, W, dh, slen):
    x = np.asarray(x, float); x = x / np.linalg.norm(x); O = np.asarray(O, float)
    ts = [(np.asarray(w) - O) @ x for w in W]; lab = set(); dirs = []; ncand = 0
    for r in ncby.get(fam(prof), []):
        if abs(r['length'] - L) > 6: continue
        for flip in (False, True):
            hs = []
            for t in ts:
                tt = (r['length'] - t) if flip else t
                c = [h for h in r['holes'] if abs(hc(h) - tt) < 2.0 and abs(h['d'] - dh) < 0.6]
                if not c: break
                hs.append(c)
            else:
                ncand += 1
                for c in hs:
                    if slen > 0 and any(isl(h) and abs(max(h['sl'], h['sw']) - slen) < 0.6 for h in c):
                        lab.add('slot'); dirs += [nc_along(h) for h in c if isl(h) and abs(max(h['sl'], h['sw']) - slen) < 0.6]
                    elif not any(isl(h) for h in c): lab.add('round')
                    else: lab.add('other_slot')
    return sorted(lab), sorted(set(str(d) for d in dirs)), ncand
rows = []; eng = None
V = db1step.V2; OH = db1step.OLDH
if V.get('V2SLOT') is not None and V.get('bgroups'):
    eng = V.get('eng'); mseq = {m['seq']: m for m in V['M']}
    for g in V['bgroups']:
        sx, sy = abs(g.get('slot_x') or 0), abs(g.get('slot_y') or 0)
        if not (sx or sy): continue
        bl = V['BG'].get(g['seq']) or []
        if not bl: continue
        W = [np.asarray(bb['p0'], float) for bb in bl]
        dh = g['d'] + (g.get('tol') or 0)
        ss = V['V2SLOT'].get(g['seq'], 'absent')
        long_ax = np.asarray(bl[0]['ex'] if sx >= sy else bl[0]['ey'], float)
        iv_ = {}
        for p_ in (V['blinks'].get(g['seq']) or []):
            w_ = [(t0_, t1_) for (bb_, t0_, t1_) in V['HP'].get(p_, []) if bb_.get('pid') == g['seq']]
            if w_: iv_[p_] = (sum(a for a, _ in w_) / len(w_) + sum(c for _, c in w_) / len(w_)) / 2
        plyord = sorted(iv_, key=lambda p_: -iv_[p_])
        for pid in (V['blinks'].get(g['seq']) or []):
            m = mseq.get(pid)
            if not m: continue
            pred = None if ss is None or ss == 'absent' else bool(ss.get(pid))
            lab, dirs, ncand = nc_label(m['O'], m['x'], m['L'], m.get('prof'), W, dh, max(sx, sy))
            xx = np.asarray(m['x'], float); xx /= np.linalg.norm(xx)
            rows.append(dict(g=g['seq'], pid=pid, prof=m.get('prof'), sx=sx, sy=sy, mask=g.get('slot_parts'), n=len(V['blinks'].get(g['seq']) or []),
                             pred=pred, why=None if ss != 'absent' else 'absent', truth=lab, ncdir=dirs, ncand=ncand,
                             palong=round(abs(float(long_ax @ xx)), 3), rank=(list(ss.keys()).index(pid) if isinstance(ss, dict) and pid in ss else None),
                             attr=g.get('attr'), flags=g.get('flags'), src=g.get('src'), prof_g=g.get('prof'), gx=round(float(np.asarray(bl[0]['ex'], float) @ xx), 3),
                             plyrank=plyord.index(pid) if pid in plyord else None, nply=len(plyord)))
elif OH.get('BL') is not None:
    eng = OH.get('eng'); mpid = {m['pid']: m for m in OH['M']}
    gb = collections.defaultdict(list)
    for bb in OH['BL']: gb[bb.get('pid')].append(bb)
    for g, bl in gb.items():
        sx, sy = (abs(float(v)) for v in (bl[0].get('slot') or (0.0, 0.0)))
        if not (sx or sy): continue
        W = [np.asarray(bb['c'], float) for bb in bl]
        dh = bl[0]['d'] + (bl[0].get('tol') or 0)
        ss = OH['SLOT_SET'].get(g, 'absent')
        parts = OH['REL10L'].get(g) or []
        for pid in parts:
            m = mpid.get(pid)
            if not m: continue
            pred = None if ss is None or ss == 'absent' else bool(ss.get(pid))
            rot = bool((OH.get('ROTP') or {}).get(g, {}).get(pid))
            long_ax = np.asarray(bl[0]['ex'] if (sx >= sy) != rot else bl[0]['ey'], float)
            lab, dirs, ncand = nc_label(m['O'], m['x'], m['L'], m.get('prof'), W, dh, max(sx, sy))
            xx = np.asarray(m['x'], float); xx /= np.linalg.norm(xx)
            rows.append(dict(rot=rot, g=g, pid=pid, prof=m.get('prof'), sx=sx, sy=sy, mask=bl[0].get('slot_mask'), n=len(parts), pred=pred,
                             why=None if ss != 'absent' else 'absent', truth=lab, ncdir=dirs, ncand=ncand, palong=round(abs(float(long_ax @ xx)), 3),
                             rank=(list(ss.keys()).index(pid) if isinstance(ss, dict) and pid in ss else None), bstr=bl[0].get('_prof'),
                             gx=round(float(np.asarray(bl[0]['ex'], float) @ xx), 3)))
GATTR = {}
if V.get('V2SLOT') is not None and V.get('bgroups'):
    db_ = V['db']
    for g in V['bgroups']:
        if not (abs(g.get('slot_x') or 0) or abs(g.get('slot_y') or 0)): continue
        try:
            rr = [o for o in db_.lookup_all(g['attr']) if int(db_.I([o + 13])[0]) == 10]
            if not rr: continue
            S_ = int(db_.lookup_stride([g['attr']])[0]); o_ = int(rr[0])
            GATTR[g['seq']] = dict(S=S_, full=bytes(db_.b[o_:o_ + S_]).hex())
        except Exception as ex_:
            GATTR[g['seq']] = dict(err=repr(ex_)[:100])
if OH.get('BL') is not None:
    import db1old, struct
    AO = getattr(db1old, 'ATTR_OFF', {}); RAW = getattr(db1old, 'RAW', b'')
    mp = {m['pid']: m for m in OH['M']}
    for g in {r['g'] for r in rows}:
        bm = [m for m in OH['M'] if m['pid'] == g]
        if not bm: continue
        q = AO.get(bm[0].get('attr'))
        if q is None: continue
        rec = RAW[q:q + 373]
        mrec = RAW[bm[0]['off']:bm[0]['off'] + bm[0]['stride']] if bm[0].get('off') is not None else b''
        GATTR[g] = dict(i32=[struct.unpack_from('<i', rec, k)[0] for k in range(0, 120, 4)], hex=rec[:124].hex(), full=rec.hex(), mrec=mrec.hex(), mstride=bm[0].get('stride'))
json.dump(dict(gattr=GATTR, db1=p, engine=eng, status=st.get('status') if isinstance(st, dict) else None, nc=len(NC), rows=rows), open(outp, 'w'), default=float)
c = collections.Counter((r['pred'], tuple(r['truth'])) for r in rows)
print(os.path.basename(p), eng, 'NC', len(NC), 'rows', len(rows), c.most_common(8))
