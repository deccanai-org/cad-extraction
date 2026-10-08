"""v2 (eng): Tekla FITTINGS (planar end trims of a part) from the DB1's own records.
8.07 (validated vs Tekla IFC): relation record (stride 69) type 9: parent part @17, fitting object @21. The fitting object
is a record keyed by its id whose int @13 is a csys key (stride-61 'after' table) and whose doubles @17/@25/@33 are a point
on the plane; the plane normal is x cross y of that csys. A fitting removes the part on the far side of the plane from the
part's middle; Tekla's IFC export writes such parts with the extrusion shortened to the plane plus an IfcHalfSpaceSolid.
The relation layout, the type value and the fitting record stride are detected per file (signature, not version)."""
import numpy as np, collections


def _csys_map(cs, lay):
    for c in cs:
        if c['stride'] == lay.get('csys_stride') and c['k'] == lay.get('csys_k') and c['key'] == 'after':
            return c['map']
    return None


def find(db, cs, lay, M, force_type=None):
    """-> ({part_seq: [(point, unit normal)]}, info)"""
    cmap = _csys_map(cs, lay)
    info = dict(relation=None, type=None, fit_stride=None, fittings=0, parts=0)
    if cmap is None: return {}, info
    seq = {m['seq'] for m in M}
    rl = getattr(db, 'cut_layout', None) or dict(stride=69, parent=17, cut=21)
    recs = db.bystride.get(rl['stride'])
    if recs is None: return {}, info
    typ = db.I(recs + 13); par = db.I(recs + rl['parent']); ch = db.I(recs + rl['cut'])
    ok = np.array([int(p) in seq for p in par]) & np.array([int(c) not in seq for c in ch])
    # candidate fitting records: keyed by the child, int@13 in the csys map, plausible point @17
    best = None
    for t in ([force_type] if force_type is not None else np.unique(typ[ok])):
        sel = np.nonzero(ok & (typ == t))[0]
        if len(sel) < 1: continue
        stc = collections.Counter(); found = {}
        for i in sel[:2000]:
            c = int(ch[i])
            for S, (K, O) in db.seqidx.items():
                if S < 45: continue
                lo, hi = np.searchsorted(K, c, 'left'), np.searchsorted(K, c, 'right')
                for o in O[lo:hi]:
                    o = int(o); ck = int(db.I([o + 13])[0])
                    if ck not in cmap: continue
                    P = db.D(o + np.array([17, 25, 33]))
                    if not np.all(np.isfinite(P)) or np.any(np.abs(P) > db.PLAUS_MAX): continue
                    stc[S] += 1; found[i] = (o, S, ck, P)
        if stc: info.setdefault('by_type', {})[int(t)] = (len(sel), sum(stc.values()))
        if stc and (best is None or sum(stc.values()) > best[0]):
            best = (sum(stc.values()), int(t), stc.most_common(1)[0][0], found, len(sel))
    if not best or best[0] < 0.8 * best[4]: return {}, info
    _, t, S, found, nsel = best
    out = collections.defaultdict(list)
    for i, (o, S_, ck, P) in found.items():
        if S_ != S: continue
        x, y = cmap[ck]; n = np.cross(x, y); nn = np.linalg.norm(n)
        if nn < 1e-9: continue
        out[int(par[i])].append((P, n / nn))
    info.update(relation=rl, type=t, fit_stride=S, fittings=sum(len(v) for v in out.values()), parts=len(out), candidates=nsel)
    return dict(out), info


def trim(m, planes, tol=1e-4):
    """member end trims along its axis from fitting planes -> (t0, t1) kept interval in [0, L] measured from O along x,
    plus the oblique planes that need a clipping cut [(P, n_out)] (n_out points to the removed side)."""
    O, x, L = m['O'], m['x'], m['L']
    t0, t1 = 0.0, L; oblique = []
    mid = O + x * L / 2
    for P, n in planes:
        s = float((mid - P) @ n)
        n_out = -n if s > 0 else n               # normal pointing to the removed side
        c = float(n_out @ x)
        if abs(c) < 1e-6: continue               # plane parallel to the axis: not an end fitting
        tp = float((P - O) @ n_out) / c          # where the axis meets the plane
        if abs(abs(c) - 1) < tol:
            if c > 0: t1 = min(t1, tp)
            else: t0 = max(t0, tp)
        else:
            oblique.append((P, n_out, tp, c))
    return t0, t1, oblique


FIT_TYPE = 9        # relation type: Tekla fitting (trims the part; validated 7.64 / 8.07 / 8.53 / 8.85 / 9.08)
LINECUT_TYPE = 12   # relation type: Tekla line cut (removes the +normal side; validated 8.07 / 8.53 / 8.85 / 9.08)


def decode_all(db, cs, lay, M):
    """-> (fittings {seq: [(P, n)]}, line cuts {seq: [(P, n)]}, info)"""
    F, i1 = find(db, cs, lay, M, FIT_TYPE)
    C, i2 = find(db, cs, lay, M, LINECUT_TYPE)
    return F, C, dict(fittings=i1.get('fittings', 0), fitted_parts=i1.get('parts', 0), line_cuts=i2.get('fittings', 0),
                      line_cut_parts=i2.get('parts', 0), fit_stride=i1.get('fit_stride') or i2.get('fit_stride'))


def plan(m, fits, lcuts, extrusion=True):
    """-> (member dict to write (trimmed for perpendicular fittings on extrusions), [(P, n_out)] half-spaces to subtract, notes)"""
    hs = []; t0, t1 = 0.0, m['L']; notes = {}
    if fits:
        a, b, obl = trim(m, fits, tol=1e-6)
        if extrusion and b - a > 1.0:
            t0, t1 = a, b
        else:
            # plates / degenerate trims: subtract the perpendicular planes as half-spaces too
            for P, n in fits:
                mid = m['O'] + m['x'] * m['L'] / 2
                n_out = -n if float((mid - P) @ n) > 0 else n
                if abs(float(n_out @ m['x'])) >= 1 - 1e-6: hs.append((P, n_out))
            notes['trim_skipped'] = True
        hs += [(P, n_out) for P, n_out, tp, c in obl]
    for P, n in lcuts:
        hs.append((P, n))
    mm = m
    if t0 > 1e-6 or t1 < m['L'] - 1e-6:
        x = m['x']
        mm = dict(m, O=m['O'] + x * t0, E=m['O'] + x * t1, L=float(t1 - t0))
        notes['trim'] = (round(t0, 2), round(m['L'] - t1, 2))
    return mm, hs, notes


def halfspace_cut(out, P, n_out, size):
    """cut tuple (frame, profile, depth) for IfcOut.element: a box of size x size on the removed side of the plane"""
    n_out = np.asarray(n_out, float) / np.linalg.norm(n_out)
    a = np.array([1.0, 0, 0]) if abs(n_out[0]) < 0.9 else np.array([0, 1.0, 0])
    X = a - (a @ n_out) * n_out; X /= np.linalg.norm(X)
    key = round(size, -1)
    prof = out.profile('HALFSPACE_%g' % key, 'RECT', [key, key])
    return ((np.asarray(P, float), n_out, X), prof, float(key / 2))
