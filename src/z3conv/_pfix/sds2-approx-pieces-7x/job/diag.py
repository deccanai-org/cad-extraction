#!/usr/bin/env python3
"""diag.py DECODE_DIR JOB OUT.json [NDUMP]
For every unique placed plate / rolled / BLT piece whose exact B-rep brep_placed() rejects, record the reason and
topology diagnostics (edge-use histogram, keyholes / spikes, T-junctions, duplicate vertices, non-planar faces,
free edges after sewing with their nearest vertices). Dumps the raw V / faces of up to NDUMP failing pieces."""
import sys, os, json, collections, time, struct
import numpy as np

DEC = sys.argv[1]; sys.path.insert(0, DEC)
job = sys.argv[2]; out = sys.argv[3]
ndump = int(sys.argv[4]) if len(sys.argv) > 4 else 40
import to_step2 as T2, brep
from piece_table import read_pieces, kind
from sds2job import read_members, REFERENCE_TYPES, read_version, read_shapes
from instances import material_instances

T2.USE_HOLES = False
T2.SHARED = True
MM = 25.4
t0 = time.time()
pieces = read_pieces(job)
mems, _ = read_members(job)
if hasattr(T2, "SHAPES"):
    try:
        T2.SHAPES = read_shapes(job)
    except Exception:
        pass
mtype = {m.id: m.type for m in mems}
try:
    ver = read_version(job)
except Exception:
    ver = None
cnt = collections.Counter(); mt_of = collections.defaultdict(set)
for n in sorted(mtype):
    if mtype[n] == "Ref Point" or mtype[n] in REFERENCE_TYPES:
        continue
    try:
        main, inst = material_instances(job, n, pieces)
    except OSError:
        continue
    for sid, M, o in inst:
        p = pieces[sid]; k = kind(p)
        if (k in ("plate", "rolled") and not T2.TURNED.match(p["name"]) or p["name"].startswith("BLT")) \
                and not p["name"].startswith("Conc"):
            cnt[sid] += 1; mt_of[sid].add(mtype[n])


def edge_hist(F):
    E = collections.Counter()
    for f in F:
        for l in brep.loops_of(f):
            for a, b in zip(l, l[1:] + l[:1]):
                if a != b:
                    E[(min(a, b), max(a, b))] += 1
    return E


def parse_explain(b):
    res = []
    for li, (hdr, vrec, lrec, frec, co, marker) in enumerate(brep.LAYOUTS):
        if len(b) < hdr + 12:
            res.append((li, "short")); continue
        nv, nf, ne = struct.unpack(">3I", b[hdr:hdr + 12])
        if not (3 < nv < 200000 and 0 < nf < 100000 and nf <= ne < 1000000):
            res.append((li, f"counts nv={nv} nf={nf} ne={ne}")); continue
        v0 = hdr + 16
        if v0 + vrec * nv + lrec * ne > len(b):
            res.append((li, f"overrun nv={nv} nf={nf} ne={ne} len={len(b)}")); continue
        V = np.array([struct.unpack(">3d", b[v0 + vrec * i:v0 + vrec * i + 24]) for i in range(nv)])
        if not np.isfinite(V).all() or np.abs(V).max() > 1e5:
            res.append((li, "bad vertices")); continue
        l0 = v0 + vrec * nv
        loops = [struct.unpack(">I", b[l0 + lrec * k:l0 + lrec * k + 4])[0] for k in range(ne)]
        if max(loops) >= nv:
            res.append((li, f"loop index {max(loops)} >= nv {nv}")); continue
        f0 = l0 + lrec * ne
        if f0 + frec * nf > len(b):
            res.append((li, f"face overrun nv={nv} nf={nf} ne={ne} len={len(b)}")); continue
        counts = [struct.unpack(">H", b[f0 + frec * k + co:f0 + frec * k + co + 2])[0] for k in range(nf)]
        res.append((li, f"face counts sum {sum(counts)} vs ne {ne}; min {min(counts)} max {max(counts)}"))
    return res


def free_edges(V, F):
    """Replicates brep._solid's face construction; returns (n faces built, n free edges, free-edge endpoints)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace, BRepBuilderAPI_Sewing
    from OCP.gp import gp_Pnt
    from OCP.BRep import BRep_Tool
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.ShapeFix import ShapeFix_Face
    W = V
    sew = BRepBuilderAPI_Sewing(1e-3 * MM); n = 0; failed = []

    def wire(idx):
        poly = BRepBuilderAPI_MakePolygon()
        for i in idx: poly.Add(gp_Pnt(*(W[i] * MM)))
        poly.Close()
        return poly.Wire() if poly.IsDone() else None
    for fi, f in enumerate(F):
        ls = brep.loops_of(f)
        if not ls:
            failed.append(fi); continue
        ls.sort(key=lambda l: -brep._area(W[l]))
        w0 = wire(ls[0])
        if w0 is None:
            failed.append(fi); continue
        mf = BRepBuilderAPI_MakeFace(w0, True)
        if not mf.IsDone():
            failed.append(fi); continue
        for l in ls[1:]:
            w = wire(l)
            if w is not None: mf.Add(w)
        face = mf.Face()
        if len(ls) > 1:
            fx = ShapeFix_Face(face); fx.FixOrientation(); fx.Perform(); face = fx.Face()
        sew.Add(face); n += 1
    pts = []
    try:
        sew.Perform()
        nfe = sew.NbFreeEdges()
        for i in range(1, min(nfe, 40) + 1):
            e = sew.FreeEdge(i)
            v1 = TopExp.FirstVertex_s(TopoDS.Edge_s(e)); v2 = TopExp.LastVertex_s(TopoDS.Edge_s(e))
            p1 = BRep_Tool.Pnt_s(v1); p2 = BRep_Tool.Pnt_s(v2)
            pts.append([[p1.X() / MM, p1.Y() / MM, p1.Z() / MM], [p2.X() / MM, p2.Y() / MM, p2.Z() / MM]])
        nmult = sew.NbMultipleEdges()
    except Exception as e:
        return n, -1, [], failed, -1
    return n, nfe, pts, failed, nmult


def nearest(V, p):
    d = np.linalg.norm(V - np.asarray(p), axis=1); i = int(d.argmin()); return i, float(d[i])


def diag_piece(sid, p):
    path = os.path.join(job, "subm", str(sid))
    d = dict(sid=sid, name=p["name"], kind=kind(p), wt=round(float(p["wt"]), 3), L=round(float(p["L"]), 4),
             W=round(float(p["W"]), 4), T=round(float(p["T"]), 4), sec=int(p["sec"]), n_inst=cnt[sid],
             member_types=sorted(mt_of[sid]), why=T2.BREP_WHY.get((job, sid)))
    try:
        data = open(path, "rb").read()
    except OSError:
        d["file"] = "missing"; return d, None
    d["size"] = len(data)
    lay = None
    for li, Lo in enumerate(brep.LAYOUTS):
        r = brep.parse(data, *Lo)
        if r is not None:
            lay = li; break
    d["layout"] = lay
    if lay is None:
        d["parse_explain"] = parse_explain(data)
        return d, None
    V, F = r
    d["nv"] = len(V); d["nf"] = len(F)
    used = sorted({i for f in F for i in f})
    d["n_used_v"] = len(used)
    ext = np.ptp(V[used], 0); d["ext"] = [round(float(x), 4) for x in sorted(ext)]
    LS = [brep.loops_of(f) for f in F]
    d["multi_loop_faces"] = sum(len(l) > 1 for l in LS)
    d["nonsimple_loops"] = sum(1 for ls in LS for l in ls if len(set(l)) < len(l))
    # loops with an edge traversed both ways (keyhole bridge) or a spike a-b-a
    kh = 0; sp = 0
    for ls in LS:
        for l in ls:
            n = len(l); es = {(l[k], l[(k + 1) % n]) for k in range(n)}
            if any((b, a) in es for a, b in es): kh += 1
            if any(l[(k - 1) % n] == l[(k + 1) % n] for k in range(n)): sp += 1
    d["keyhole_loops"] = kh; d["spike_loops"] = sp
    E = edge_hist(F); h = collections.Counter(E.values()); d["edge_use"] = {str(k): v for k, v in sorted(h.items())}
    # duplicate vertex coordinates among used vertices
    key = {}; dupv = 0
    for i in used:
        t = tuple(np.round(V[i] / 1e-4).astype(np.int64))
        if t in key: dupv += 1
        else: key[t] = i
    d["dup_vertices"] = dupv
    # planarity / degenerate loops
    npl = 0; maxdev = 0.0; zero = 0; short = 0
    for ls in LS:
        if not ls: short += 1; continue
        P = V[ls[0]]; c = P.mean(0)
        nrm = sum(np.cross(P[k] - c, P[(k + 1) % len(P)] - c) for k in range(len(P)))
        if np.linalg.norm(nrm) < 1e-10: zero += 1; continue
        nrm /= np.linalg.norm(nrm)
        for l in ls:
            dev = float(np.abs((V[l] - c) @ nrm).max())
            maxdev = max(maxdev, dev)
            if dev > 1e-3: npl += 1
    d["nonplanar_loops"] = npl; d["max_plane_dev"] = round(maxdev, 5); d["zero_area_faces"] = zero
    d["faces_lt3_loops"] = short
    # T-junctions: used vertices strictly inside a loop edge
    P = V[used]; tj = 0
    for ls in LS:
        for l in ls:
            for a, b in zip(l, l[1:] + l[:1]):
                dv = V[b] - V[a]; L2 = dv @ dv
                if L2 < 1e-12: continue
                t = (P - V[a]) @ dv / L2
                off = np.linalg.norm(P - V[a] - np.outer(t, dv), axis=1)
                tj += int(((t > 1e-6) & (t < 1 - 1e-6) & (off < 1e-4)).sum())
    d["t_junctions"] = tj
    try:
        F2 = brep.conform(V, F); h2 = collections.Counter(edge_hist(F2).values())
        d["edge_use_conform"] = {str(k): v for k, v in sorted(h2.items())}
    except Exception as e:
        d["edge_use_conform"] = f"error {type(e).__name__}"
    try:
        n, nfe, pts, failed, nmult = free_edges(V, F)
        d["faces_built"] = n; d["faces_failed"] = failed[:20]; d["n_faces_failed"] = len(failed)
        d["free_edges"] = nfe; d["multiple_edges"] = nmult
        d["free_edge_vertices"] = [[nearest(V[used], a)[0], nearest(V[used], b)[0]] for a, b in pts[:12]]
    except Exception as e:
        d["free_edges"] = f"error {type(e).__name__}: {e}"
    # does it build at all (with repairs) and how heavy is it vs SDS2
    try:
        sh = brep.solid(V, F)
        d["solid_builds"] = sh is not None
        if sh is not None:
            from OCP.GProp import GProp_GProps
            from OCP.BRepGProp import BRepGProp
            g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g)
            vol = abs(g.Mass()) / MM ** 3
            d["vol_in3"] = round(vol, 3)
            if p["wt"] > 0: d["ratio"] = round(vol * 0.2836 / p["wt"], 4)
    except Exception as e:
        d["solid_builds"] = f"error {type(e).__name__}"
    dump = None
    if len(V) <= 600:
        dump = dict(sid=sid, name=p["name"], V=np.round(V, 6).tolist(), F=[list(map(int, f)) for f in F],
                    raw_faces=None)
    return d, dump


res = []; dumps = []; ok = 0; inst_ok = 0; inst_bad = 0; repaired = []; ok_sids = []; weight_notes = []


def bbox_in(sh):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    bb = Bnd_Box(); BRepBndLib.Add_s(sh, bb)
    a, b = bb.CornerMin(), bb.CornerMax()
    return np.array([b.X() - a.X(), b.Y() - a.Y(), b.Z() - a.Z()]) / MM


for sid in sorted(cnt, key=lambda s: -cnt[s]):
    p = pieces[sid]
    if hasattr(T2, "PLACING_REF"):
        T2.PLACING_REF = any((t or "").strip().upper().replace(" ", "") == "REFERENCEMODEL" for t in mt_of[sid])
    r = T2.brep_placed(job, sid, p, np.eye(3), np.zeros(3))
    rep = getattr(brep, "LAST_REPAIR", "")
    wnote = getattr(T2, "BREP_WEIGHT_NOTE", {}).get((job, sid))
    if r is not None:
        ok += 1; inst_ok += cnt[sid]; ok_sids.append(sid)
        if wnote:
            weight_notes.append(dict(sid=sid, name=p["name"], n_inst=cnt[sid], note=wnote,
                                     member_types=sorted(mt_of[sid])))
        if rep:
            try:
                from OCP.GProp import GProp_GProps
                from OCP.BRepGProp import BRepGProp
                sh = r[1]
                g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g); vol = abs(g.Mass()) / MM ** 3
                V_, F_ = brep.parse(open(os.path.join(job, "subm", str(sid)), "rb").read())
                used = sorted({i for f in F_ for i in f})
                ext = np.ptp(V_[used], 0); bx = bbox_in(sh)
                repaired.append(dict(sid=sid, name=p["name"], n_inst=cnt[sid], repair=rep, vol_in3=round(vol, 3),
                                     ratio=round(vol * 0.2836 / p["wt"], 4) if p["wt"] > 0 else None,
                                     bbox_dev=round(float(np.abs(np.sort(bx) - np.sort(ext)).max()), 4),
                                     ext=[round(float(x), 3) for x in sorted(ext)]))
            except Exception as e:
                repaired.append(dict(sid=sid, name=p["name"], repair=rep, error=str(e)))
        continue
    inst_bad += cnt[sid]
    try:
        d, dump = diag_piece(sid, p)
    except Exception as e:
        d, dump = dict(sid=sid, name=p["name"], error=f"{type(e).__name__}: {e}"), None
    res.append(d)
    if dump is not None and len(dumps) < ndump:
        dumps.append(dump)
why = collections.Counter(); why_i = collections.Counter()
for d in res:
    w = (d.get("why") or "?")
    w = "weight ratio" if "outside 0.6-1.6" in w else w
    why[w] += 1; why_i[w] += d.get("n_inst", 0)
summary = dict(job=os.path.basename(job), version=ver, decode=DEC, unique_ok=ok, unique_bad=len(res), inst_ok=inst_ok,
               inst_bad=inst_bad, why_unique=dict(why), why_inst=dict(why_i), n_repaired=len(repaired),
               inst_repaired=sum(d.get("n_inst", 0) for d in repaired), n_weight_notes=len(weight_notes),
               inst_weight_notes=sum(d["n_inst"] for d in weight_notes), sec=round(time.time() - t0, 1))
json.dump(dict(summary=summary, pieces=res, repaired=repaired, ok_sids=ok_sids, weight_notes=weight_notes),
          open(out, "w"), indent=0, default=str)
json.dump(dumps, open(os.path.splitext(out)[0] + "_dump.json", "w"), default=str)
print(json.dumps(summary))
