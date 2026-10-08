#!/usr/bin/env python3
"""probe parts for 6.1.8 items. usage: fix_probe.py CONVERTER.py IFC MODE GUID [GUID...]
MODE l1 : per part, OCC verdict of L0 (as written), L0 without coplanar merge, L1 triangulated (+ BRepCheck statuses)
MODE gap: per part, free edges after repair and the max gap to the nearest other free edge (mm)"""
import sys, os, json, tempfile, collections, importlib.util
spec = importlib.util.spec_from_file_location('v6', sys.argv[1]); V = importlib.util.module_from_spec(spec); spec.loader.exec_module(V)
import ifcopenshell, ifcopenshell.util.unit, numpy as np
f = ifcopenshell.open(sys.argv[2]); mode = sys.argv[3]; gids = sys.argv[4:]
sc = ifcopenshell.util.unit.calculate_unit_scale(f) * 1000
tc = V.Transcoder(f, sc)


def pieces_of(p):
    items, _ = V.body_items(p)
    return tc.product(p, items)


def verify(bp, p):
    X, solids, surfaces, tags = bp
    td = tempfile.mkdtemp(); sp = V.Spool(os.path.join(td, 's.bin'), 2)
    fr = sp.emit(p.Name, p.GlobalId, p.is_a(), solids, surfaces, X); sp.close()
    hdr, gents = V.header_text('probe'); out = os.path.join(td, 'p.step')
    with open(out, 'wb') as o, open(sp.path, 'rb') as s_:
        o.write(hdr.encode()); o.write(gents.encode()); o.write(s_.read()); o.write(V.TAIL.encode())
    lf = os.path.join(td, 'l.json'); of = os.path.join(td, 'o.jsonl'); json.dump([out], open(lf, 'w'))
    V.verify_worker(lf, of)
    try:
        r = json.loads(open(of).readline())
    except Exception:
        r = None
    ok, why = V.judge(r, fr)
    return ('pass' if ok else why), (r or {}).get('valid'), fr.nfaces


def free_edges(faces, nv):
    A, B, F = V.Repair.edge_arrays(faces)
    key = np.minimum(A, B) * nv + np.maximum(A, B)
    uk, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    m = cnt[inv] == 1
    return A[m], B[m]


def seg_dist(P, a, b):
    d = b - a; L2 = float(d @ d)
    if L2 <= 0:
        return np.linalg.norm(P - a, axis=1)
    t = np.clip(((P - a) @ d) / L2, 0, 1)
    return np.linalg.norm(P - (a + np.outer(t, d)), axis=1)


for g in gids:
    p = f.by_guid(g)
    pcs = pieces_of(p)
    if pcs is None:
        print(json.dumps({'gid': g, 'note': 'not transcodable'})); continue
    if mode == 'l1':
        res = {'gid': g, 'cls': p.is_a(), 'name': p.Name}
        rep = V.Repair(2); res['L0'] = verify(V.build_part(pcs, rep), p); res['L0_repair'] = dict(rep.stats)
        rep = V.Repair(2); rep.merge = False; res['L0_nomerge'] = verify(V.build_part(pcs, rep), p)
        rep = V.Repair(2); res['L1'] = verify(V.build_part(pcs, rep, tri=True), p)
        print(json.dumps(res), flush=True)
    else:
        rep = V.Repair(2)
        Vs = np.concatenate([pc.V for pc in pcs]); Q, inv = rep.weld(Vs); X = Q / 100.0
        gaps = []; nfree = 0; off = 0
        for pc in pcs:
            faces = [[[i + off for i in lp] for lp in fc] for fc in pc.faces]; off += len(pc.V)
            if pc.role not in ('solid', 'closed_surface'):
                continue
            fs = rep.clean_faces(faces, inv, X); fs = rep.dedup_faces(fs)
            fs, _ = rep.sew(fs, X, rep.tol_sew); fs, _ = rep.tjunctions(fs, X)
            a, b = free_edges(fs, len(X))
            nfree += len(a)
            for k in range(len(a)):
                # nearest OTHER free edge: max distance of this edge's endpoints (and midpoint) to that segment
                P = np.array([X[a[k]], X[b[k]], (X[a[k]] + X[b[k]]) / 2])
                best = None
                for j in range(len(a)):
                    if j == k: continue
                    dd = float(seg_dist(P, X[a[j]], X[b[j]]).max())
                    best = dd if best is None or dd < best else best
                gaps.append(best if best is not None else float('inf'))
        print(json.dumps({'gid': g, 'cls': p.is_a(), 'name': p.Name, 'free_edges': nfree,
                          'gap_max_mm': (round(max(gaps), 4) if gaps else 0.0), 'gap_p50_mm': (round(float(np.median(gaps)), 4) if gaps else 0.0)}), flush=True)
