"""Score the decoder on DB1+IFC pairs: precision = decoded members that coincide with an IFC
extrusion (both axis ends < 2 mm), plus profile-name and orientation agreement."""
import sys, os, json, pickle, collections, time, traceback, glob
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db1dec import decode, members
def score(db1, ifcpkl, layout=None, variants=()):
    try:
        T = pickle.load(open(ifcpkl, 'rb')) if os.path.exists(ifcpkl) else []
        t0 = time.time(); db, pts, cs, lay = decode(db1, layout, variants, True)
        if not lay: return dict(err='no member layout', ifc=len(T), secs=round(time.time() - t0, 1), mb=round(db.L / 1e6, 1))
        M = members(db, pts, cs, lay)
        A = np.array([t['a'] for t in T]) if T else np.zeros((0, 3)); Bq = np.array([t['b'] for t in T]) if T else np.zeros((0, 3))
        # IFC may be exported relative to a base point and ROTATED about Z: vote a rotation from
        # horizontal members of equal length and profile, then a translation.
        shift = np.zeros(3); votes = 0; Rz = np.eye(3); ang = 0.0
        if len(T) and M:
            Lt = np.array([t['L'] for t in T]); Dt = (Bq - A) / np.maximum(Lt[:, None], 1e-9)
            order = np.argsort(Lt); Ls = Lt[order]
            av = collections.Counter()
            Ms = [m for m in M if abs(m['x'][2]) < 0.05 and m['L'] > 300][:4000]
            for m in Ms[:: max(1, len(Ms) // 1500)]:
                lo, hi = np.searchsorted(Ls, m['L'] - 0.5), np.searchsorted(Ls, m['L'] + 0.5)
                a0 = np.degrees(np.arctan2(m['x'][1], m['x'][0]))
                for j in order[lo:hi][:30]:
                    if abs(Dt[j][2]) > 0.05 or (m['prof'] and T[j]['prof'] and m['prof'] != T[j]['prof']): continue
                    a1 = np.degrees(np.arctan2(Dt[j][1], Dt[j][0]))
                    for d in (a1 - a0, a1 - a0 + 180):
                        av[round(((d + 180) % 360) - 180, 1)] += 1
            if av:
                (ang, n_), = av.most_common(1)
                if n_ >= 5:
                    c, s_ = np.cos(np.radians(ang)), np.sin(np.radians(ang)); Rz = np.array([[c, -s_, 0], [s_, c, 0], [0, 0, 1]])
            vote = collections.Counter()
            for m in M[:: max(1, len(M) // 3000)]:
                O = Rz @ m['O']; xd = Rz @ m['x']
                lo, hi = np.searchsorted(Ls, m['L'] - 0.5), np.searchsorted(Ls, m['L'] + 0.5)
                for j in order[lo:hi][:40]:
                    if abs(abs(Dt[j] @ xd) - 1) > 1e-4: continue
                    for d in (A[j] - O, Bq[j] - O):
                        vote[tuple(np.round(d, 0))] += 1
            if vote:
                (sh, votes), = vote.most_common(1)
                if votes >= 5: shift = np.array(sh, float)
        for m in M:
            m['O'] = Rz @ m['O'] + shift; m['E'] = Rz @ m['E'] + shift
            m['x'] = Rz @ m['x']; m['xr'] = Rz @ m['xr']; m['y'] = Rz @ m['y']
        shift_applied = shift.copy(); shift = np.zeros(3)
        used = np.zeros(len(T), bool); st = collections.Counter(); badp = collections.Counter()
        for m in M:
            if not len(T): break
            O = m['O'] + shift; E = m['E'] + shift
            d = np.minimum(np.linalg.norm(A - O, axis=1) + np.linalg.norm(Bq - E, axis=1),
                           np.linalg.norm(Bq - O, axis=1) + np.linalg.norm(A - E, axis=1))
            d[used] = 1e18; j = int(np.argmin(d))
            if d[j] < 3:
                used[j] = True; st['match'] += 1
                if m['prof'] == T[j]['prof']: st['prof_ok'] += 1
                else: st['prof_diff'] += 1; badp[(m['prof'], T[j]['prof'])] += 1
                st['y_ok' if abs(m['y'] @ T[j]['R'][:, 1]) > 0.999 else 'y_bad'] += 1
                # the IFC writer's frame must equal Tekla's: Z = -x_raw, X = x_raw cross y
                R = T[j]['R']
                st['frame_ok' if (abs(-m['xr'] @ R[:, 2] - 1) < 1e-4 and abs(np.cross(m['xr'], m['y']) @ R[:, 0] - 1) < 1e-4) else 'frame_bad'] += 1
        st['shift'] = [float(x) for x in shift_applied]; st['shift_votes'] = votes; st['rot_deg'] = float(ang)
        return dict(secs=round(time.time() - t0, 1), mb=round(db.L / 1e6, 1), members=len(M),
                    noprof=sum(1 for m in M if not m['prof']), ifc=len(T),
                    ifc_cls=dict(collections.Counter(t['cls'] for t in T)), **st,
                    prof_diff_top=[list(k) + [v] for k, v in badp.most_common(6)],
                    lay={k: v for k, v in lay.items()})
    except Exception:
        return dict(err=traceback.format_exc()[-600:])
