"""Regression metrics for an SDS2 -> STEP conversion, computed from the STEP read back with OCC and the job's own data
(independent of the converter's builders). Implements the metrics the FIX documents use:

  M1  per-family mass ratio: solid volume x 0.2836 lb/in3 / SDS2 weight (stage 2: piece-table weight per piece;
      stage 1: job_mtrl lb/ft x member length)
  M2  stage-1 / stage-2 joists: share of joists written as solid blocks (mass > 3x SDS2's weight per foot)
  S3  duplicate solid names
  G4  the same piece at the same place written for two different members (converter-introduced vs SDS2 twins)
  G5  piece box in the piece's own frame vs the box rebuilt from the job's vertex records (stray points dropped,
      EC-45 rule): share within 0.1 in, per family; legs-swapped count for angles
  H   hollow check: face counts of rectangular HSS pieces (>= 10 = hollow)
  N   counts: placed instances decoded from the job, solids written, skipped

usage: python v5check.py <job_dir> <file.step> [--stage 1|2] [-o metrics.json]
"""
import os, sys, re, json, math, argparse, collections, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "decode"))

MM = 25.4
PLACED_VALIDITY = False   # --placed-validity: BRepCheck every placed instance (names of invalid ones)
INVALID_PLACED = []
NAME = re.compile(r"^(?P<mt>.+?) #(?P<n>\d+) / (?P<pn>.*?) \(piece (?P<sid>\d+)(?:, inst (?P<inst>\d+))?(?:,[^)]*)?\)")
ENV = re.compile(r"^(?P<mt>.+?) #(?P<n>\d+) / (?P<pn>.*?) \((?:member envelope|joist[^)]*)\)")
S1 = re.compile(r"^(?P<mt>.+?) (?P<sec>\S+) #(?P<n>\d+)")


def family(name):
    n = name.strip()
    if re.match(r"BPL", n): return "BPL"
    if re.match(r"PIPE", n): return "ROUND"
    if re.match(r"HSS", n):
        return "ROUND" if n.lower().count("x") == 1 else "HSS"
    m = re.match(r"[A-Z]+", n)
    return m.group() if m else "?"


def read_step(path):
    """-> list of instances dict(name, part, trsf) and parts {key: dict(vol, faces, V (in, local), cyl)}"""
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
    from OCP.TDF import TDF_Label
    try:
        from OCP.TDF import TDF_LabelSequence
    except ImportError:                                   # OCP 8.x: NCollection sequences live in OCP.collections
        from OCP.collections import Sequence_TDF_Label as TDF_LabelSequence
    from OCP.TDataStd import TDataStd_Name
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE, TopAbs_VERTEX, TopAbs_SOLID
    from OCP.TopoDS import TopoDS
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.BRepCheck import BRepCheck_Analyzer
    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    rd = STEPCAFControl_Reader(); rd.SetNameMode(True)
    if rd.ReadFile(path) != IFSelect_RetDone:
        raise SystemExit(f"cannot read {path}")
    rd.Transfer(doc)
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

    def name_of(lab):
        a = TDataStd_Name()
        if lab.FindAttribute(TDataStd_Name.GetID_s(), a):
            return a.Get().ToExtString()
        return ""

    parts = {}

    def part_info(lab, shape):
        key = lab.Tag() if lab is not None else id(shape)
        k2 = (lab.Father().Tag(), lab.Tag()) if lab is not None else key
        if k2 in parts:
            return k2
        g = GProp_GProps(); BRepGProp.VolumeProperties_s(shape, g)
        nf = ncyl = 0
        ex = TopExp_Explorer(shape, TopAbs_FACE)
        while ex.More():
            nf += 1
            try:
                if BRepAdaptor_Surface(TopoDS.Face(ex.Current())).GetType() == GeomAbs_Cylinder: ncyl += 1
            except Exception:
                pass
            ex.Next()
        P = []
        ex = TopExp_Explorer(shape, TopAbs_VERTEX)
        while ex.More():
            p = BRep_Tool.Pnt_s(TopoDS.Vertex(ex.Current())); P.append((p.X(), p.Y(), p.Z())); ex.Next()
        nsol = 0
        ex = TopExp_Explorer(shape, TopAbs_SOLID)
        while ex.More(): nsol += 1; ex.Next()
        parts[k2] = dict(vol=abs(g.Mass()) / MM ** 3, faces=nf, cyl=ncyl, solids=nsol,
                         V=np.unique(np.round(np.array(P) / MM, 5), axis=0) if P else np.zeros((0, 3)),
                         valid=bool(BRepCheck_Analyzer(shape).IsValid()))
        return k2

    inst = []
    roots = TDF_LabelSequence(); st.GetFreeShapes(roots)
    for i in range(1, roots.Length() + 1):
        lab = roots.Value(i)
        if XCAFDoc_ShapeTool.IsAssembly_s(lab):
            comps = TDF_LabelSequence(); XCAFDoc_ShapeTool.GetComponents_s(lab, comps, False)
            for j in range(1, comps.Length() + 1):
                c = comps.Value(j)
                ref = TDF_Label(); XCAFDoc_ShapeTool.GetReferredShape_s(c, ref)
                shp = XCAFDoc_ShapeTool.GetShape_s(ref)
                loc = XCAFDoc_ShapeTool.GetLocation_s(c).Transformation()
                inst.append(dict(name=name_of(c) or name_of(ref), part=part_info(ref, shp), trsf=loc))
                if PLACED_VALIDITY:
                    from OCP.TopLoc import TopLoc_Location
                    if not BRepCheck_Analyzer(shp.Moved(TopLoc_Location(loc))).IsValid():
                        INVALID_PLACED.append(inst[-1]["name"])
        else:
            shp = XCAFDoc_ShapeTool.GetShape_s(lab)
            inst.append(dict(name=name_of(lab), part=part_info(lab, shp), trsf=None))
            if PLACED_VALIDITY and not parts[inst[-1]["part"]]["valid"]:
                INVALID_PLACED.append(inst[-1]["name"])
    return inst, parts


def world_pts(inst, parts):
    V = parts[inst["part"]]["V"]
    t = inst["trsf"]
    if t is None or not len(V):
        return V
    R = np.array([[t.Value(r, c) for c in (1, 2, 3)] for r in (1, 2, 3)])
    T = np.array([t.Value(r, 4) for r in (1, 2, 3)]) / MM
    return V @ R.T + T


def expected_box(job, sid, sh, cache={}):
    """Piece boxes rebuilt from the job, in the piece frame -> (faces box, records box):
    faces   = bbox of the vertices referenced by the piece file's own faces (brep.parse), None if no topology;
    records = bbox of all tagged vertex records (instances.subm_vertices) with the verifier's EC-45 rule (drop points
              farther than the section's own size from the median in y/z). Unreferenced marker records (HSS
              reference squares, work-point records) survive EC-45 when they lie within the section size."""
    from instances import subm_vertices
    import brep
    key = (job, sid)
    if key in cache: return cache[key]
    fb = rb = None
    try:
        r = brep.parse(open(os.path.join(job, "subm", str(sid)), "rb").read())
        if r is not None:
            used = sorted({i for f in r[1] for i in f})
            if len(used) >= 4:
                U = r[0][used]; fb = (U.min(0), U.max(0))
    except OSError:
        pass
    V = subm_vertices(job, sid)
    if V is not None and len(V) >= 4:
        if sh is not None:
            size = max(sh.d, sh.bf, 0.25)
            c = np.median(V[:, 1:], axis=0)
            keep = np.all(np.abs(V[:, 1:] - c) <= size + 0.1, axis=1)
            if keep.sum() >= 4:
                V = V[keep]
        rb = (V.min(0), V.max(0))
    cache[key] = (fb, rb)
    return cache[key]


def stage2(job, step):
    from piece_table import read_pieces, kind
    from sds2job import read_shapes, read_members
    from instances import material_instances
    t0 = time.time()
    inst, parts = read_step(step)
    t_read = time.time() - t0
    P = read_pieces(job); S = read_shapes(job)
    mems, _ = read_members(job)
    mem_by = {m.id: m for m in mems}
    # decoded placements (the job's truth), ordered per (member, piece) like the converter numbers instances
    placed = {}
    n_placed = 0; n_bad_frame = 0
    for m in mems:
        if m.type == "Ref Point":
            continue
        try:
            _, ins = material_instances(job, m.id, P)
        except Exception:
            continue
        cnt = collections.Counter()
        for sid, M, o in ins:
            cnt[sid] += 1
            ok = np.isfinite(M).all() and np.isfinite(o).all() and np.abs(M @ M.T - np.eye(3)).max() <= 1e-3
            if not ok:
                n_bad_frame += 1
                continue
            n_placed += 1
            placed[(m.id, sid, cnt[sid])] = (M, o)
    names = collections.Counter(i["name"] for i in inst)
    out = dict(step=os.path.basename(step), read_s=round(t_read, 1), instances=len(inst), parts=len(parts),
               invalid_parts=sum(not p["valid"] for p in parts.values()),
               decoded_placements=n_placed, decoded_phantom_blocks=n_bad_frame)
    out["S3_duplicate_names"] = sum(c - 1 for c in names.values() if c > 1)
    out["S3_examples"] = [n for n, c in names.most_common(5) if c > 1]
    if PLACED_VALIDITY:
        out["invalid_placed"] = dict(n=len(INVALID_PLACED), names=INVALID_PLACED[:50])
    fam_ratio = collections.defaultdict(list); hss_faces = []; g5 = collections.defaultdict(lambda: [0, 0, 0]); g5r = collections.defaultdict(lambda: [0, 0, 0])
    g5_examples = collections.defaultdict(list); oversize = 0; joist = dict(n=0, block=0)
    dup = collections.defaultdict(set); tagged = collections.Counter(); holes_cyl = 0; piece_inst = 0
    for it in inst:
        nm = it["name"]
        for tg in re.findall(r"\[([a-z_]+)", nm):
            tagged[tg] += 1
        m = NAME.match(nm)
        part = parts[it["part"]]
        if not m:
            e = ENV.match(nm)
            if e and e.group("mt") == "JOIST":
                mem = mem_by.get(int(e.group("n")))
                joist["n"] += 1
                if mem is not None and mem.section is not None and mem.section.d > 0:
                    L = np.linalg.norm(np.subtract(mem.p2, mem.p1))
                    if L > 0 and part["vol"] / (mem.section.d * max(mem.section.bf, 1.0) * L) > 0.5:
                        joist["block"] += 1
            continue
        n, sid, k = int(m.group("n")), int(m.group("sid")), int(m.group("inst") or 1)
        p = P.get(sid)
        if p is None:
            continue
        piece_inst += 1
        fam = family(p["name"])
        if p["name"].startswith("Conc") or re.match(r"GT\d", p["name"]):
            continue
        if 0 < p["wt"] < 1e6 and part["solids"] > 0:
            fam_ratio[fam].append(part["vol"] * 0.2836 / p["wt"])
        holes_cyl += part["cyl"]
        if fam == "HSS":
            hss_faces.append(part["faces"])
        W = world_pts(it, parts)
        if len(W):
            lo, hi = W.min(0), W.max(0)
            key = (sid, tuple(np.round((lo + hi) / 2, 1)), tuple(np.round(hi - lo, 1)))
            dup[key].add(n)
        fr = placed.get((n, sid, k))
        kd = kind(p)
        if fr is None or kd not in ("rolled", "plate") or not len(W):
            continue
        M, o = fr
        Lc = (W - o) @ M.T                         # local = M @ (w - o)
        llo, lhi = Lc.min(0), Lc.max(0)
        sh = S.get(p["sec"]) if kd == "rolled" else None
        fb, rb = expected_box(job, sid, sh)
        ext_s = lhi - llo
        gf = fam if fam in ("L", "HSS", "ROUND", "W", "C", "MC", "WT", "PL", "FL", "BPL") else ("rolled_other" if kd == "rolled" else "plate_other")
        for tag, eb, tab in (("faces", fb, g5), ("records", rb, g5r)):
            if eb is None:
                continue
            ext_e = eb[1] - eb[0]
            rec = tab[gf]; rec[0] += 1
            if np.all(np.abs(ext_s - ext_e) <= 0.1):
                rec[1] += 1
                continue
            if fam == "L" and abs(ext_s[1] - ext_e[2]) <= 0.1 and abs(ext_s[2] - ext_e[1]) <= 0.1 and abs(ext_e[1] - ext_e[2]) > 0.1:
                rec[2] += 1                        # legs exchanged
            if tag == "faces" and len(g5_examples[gf]) < 5:
                g5_examples[gf].append(dict(name=nm, step_ext=np.round(ext_s, 2).tolist(), job_ext=np.round(ext_e, 2).tolist()))
            if tag == "faces" and sh is not None and max(ext_s[1], ext_s[2]) > max(sh.d, sh.bf) + 1.0:
                oversize += 1
    out["M1_by_family"] = {f: dict(n=len(v), median=round(float(np.median(v)), 3), p10=round(float(np.percentile(v, 10)), 3),
                                   p90=round(float(np.percentile(v, 90)), 3))
                           for f, v in sorted(fam_ratio.items(), key=lambda kv: -len(kv[1])) if v}
    out["G5"] = {f: dict(n=r[0], within_0p1=r[1], share=round(r[1] / r[0], 4) if r[0] else None,
                         **({"legs_swapped": r[2]} if f == "L" else {})) for f, r in sorted(g5.items())}
    out["G5_records_EC45"] = {f: dict(n=r[0], within_0p1=r[1], share=round(r[1] / r[0], 4) if r[0] else None,
                                     **({"legs_swapped": r[2]} if f == "L" else {})) for f, r in sorted(g5r.items())}
    out["G5_examples"] = dict(g5_examples)
    out["G5_oversize_gt_1in"] = oversize
    out["HSS_faces"] = dict(n=len(hss_faces), median=float(np.median(hss_faces)) if hss_faces else None,
                            hollow_share=round(float(np.mean(np.array(hss_faces) >= 10)), 4) if hss_faces else None)
    # G4: same piece, same world box, different members (twins = identical type/section/end points)
    twins = 0; intro = 0; intro_ex = []
    sig = {m.id: (m.type, m.section.name if m.section else None, tuple(np.round(m.p1, 2)), tuple(np.round(m.p2, 2))) for m in mems}
    for key, ms in dup.items():
        if len(ms) < 2:
            continue
        sigs = collections.Counter(sig.get(x) for x in ms)
        if len(sigs) == 1:
            twins += len(ms) - 1
        else:
            intro += len(ms) - 1
            if len(intro_ex) < 5: intro_ex.append(dict(piece=key[0], members=sorted(ms)))
    out["G4"] = dict(duplicates_twin_members=twins, introduced_by_converter=intro,
                     introduced_share=round(intro / max(piece_inst, 1), 5), examples=intro_ex)
    out["joists"] = joist
    out["piece_instances_written"] = piece_inst
    out["cylindrical_faces"] = holes_cyl
    out["tags"] = dict(tagged)
    return out


def stage1(job, step):
    from sds2job import read_members
    inst, parts = read_step(step)
    mems, _ = read_members(job)
    by = {m.id: m for m in mems}
    fam = collections.defaultdict(list); joist = dict(n=0, block=0)
    for it in inst:
        m = S1.match(it["name"])
        if not m: continue
        mem = by.get(int(m.group("n")))
        if mem is None or mem.section is None or mem.section.weight <= 0: continue
        L = np.linalg.norm(np.subtract(mem.p2, mem.p1))
        if L <= 0: continue
        r = parts[it["part"]]["vol"] * 0.2836 / (mem.section.weight * L / 12)
        f = "JOIST" if mem.type == "JOIST" else family(mem.section.name)
        fam[f].append(r)
        if mem.type == "JOIST":
            # solid block = the solid fills more than half of its d x bf envelope (an open-web joist fills ~2-5 %)
            fill = parts[it["part"]]["vol"] / max(mem.section.d * max(mem.section.bf, 1.0) * L, 1e-9)
            joist["n"] += 1; joist["block"] += fill > 0.5; joist.setdefault("ratio_vs_sds2_wt", []).append(r)
    return dict(step=os.path.basename(step), instances=len(inst),
                M1_by_family={f: dict(n=len(v), median=round(float(np.median(v)), 3)) for f, v in
                              sorted(fam.items(), key=lambda kv: -len(kv[1]))},
                M2_joists=dict(n=joist["n"], block=joist["block"], block_share=round(joist["block"] / joist["n"], 4) if joist["n"] else None,
                               median_ratio_vs_sds2_record_wt=round(float(np.median(joist["ratio_vs_sds2_wt"])), 3) if joist["n"] else None),
                invalid_parts=sum(not p["valid"] for p in parts.values()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job"); ap.add_argument("step")
    ap.add_argument("--stage", type=int, default=2)
    ap.add_argument("-o", "--out")
    ap.add_argument("--placed-validity", action="store_true")
    a = ap.parse_args()
    global PLACED_VALIDITY
    PLACED_VALIDITY = a.placed_validity
    res = stage1(a.job, a.step) if a.stage == 1 else stage2(a.job, a.step)
    s = json.dumps(res, indent=1, default=float)
    if a.out:
        open(a.out, "w").write(s)
    print(s)


if __name__ == "__main__":
    main()
