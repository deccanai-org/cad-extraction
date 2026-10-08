#!/usr/bin/env python3
"""Per-piece weight dump for one SDS2 job (analysis only; agentjob sds2-weights-failures).

Runs the pipeline's own stage-2 conversion (to_step2.convert, unchanged builders) with the STEP transfer / write and the
assembly STEP check stubbed out (they do not touch the weight tally), captures the per-placement tally that
manifest.build receives (piece_dev) and the per-placement rows (builder, stand-in text), and adds per-piece diagnostics:
piece-table fields + raw slot, section catalog record, the piece's own B-rep volume (with / without its decoded holes),
special_solid / turned_local geometry for studs / rods, mesh extents.

usage: wdump.py DECODE_DIR JOB_DIR OUT_JSON [--write]
"""
import sys, os, json, time, collections, re, struct, traceback

DEC, JOB, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
WRITE = "--write" in sys.argv
sys.path.insert(0, DEC)
import numpy as np
import to_step2 as T2
import manifest as MF
import piece_table as PT
import brep
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp

MM = 25.4
DENS = 0.2836
cap = {}
_orig_build = MF.build


def _build(*a, **k):
    cap.update(rows=k.get("rows"), big=k.get("piece_dev"), weights=k.get("weights"), skipped=k.get("skipped"),
               stats=dict(k.get("stats") or {}), placed=k.get("placed"))
    return _orig_build(*a, **k)


MF.build = _build


class _NoWrite:
    def SetNameMode(self, b): pass
    def Transfer(self, *a): return True
    def Write(self, out):
        open(out, "w").close(); return T2.IFSelect_RetDone


if not WRITE:
    T2.STEPCAFControl_Writer = _NoWrite
    T2.assembly_check = lambda first: set()
T2.USE_DERIVED_HOLES = False


def vol_lb(sh):
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g)
    return abs(g.Mass()) / MM ** 3 * DENS


res = dict(job=os.path.basename(JOB.rstrip("/")), decode=DEC, started=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
t0 = time.time()
step_out = os.path.join(os.path.dirname(OUT), os.path.basename(JOB.rstrip("/")) + "_ana.step")
try:
    ok, stats = T2.convert(JOB, step_out, shared=True)
    res["convert_ok"] = bool(ok); res["stats"] = {k: v for k, v in stats.items() if isinstance(v, (int, float, str)) or v is None}
except BaseException as e:
    res["error"] = f"{type(e).__name__}: {e}"; res["traceback"] = traceback.format_exc()[-3000:]
res["convert_s"] = round(time.time() - t0, 1)
try:
    if os.path.exists(step_out) and not WRITE:
        os.remove(step_out)
except OSError:
    pass

if "big" in cap:
    try:
        pieces = PT.read_pieces(JOB)
        shapes = T2.read_shapes(JOB)
        b = open(os.path.join(JOB, "subm", "subm_idx"), "rb").read()
        key = PT.slot_size(b); Lo = PT.LAYOUTS[key]; SLOT = Lo["slot"]
        res["piece_layout"] = str(key)
        w = cap["weights"] or {}
        res["weights"] = dict(step_lb=w.get("step_lb"), sds2_lb=w.get("sds2_lb"), by_family=w.get("by_family"),
                              by_source=w.get("by_source"), turned_brep=w.get("turned_brep"))
        res["skipped_by_reason"] = dict(collections.Counter(x.get("reason") for x in (cap.get("skipped") or [])))
        per = {}
        for d, wt, name, sid in cap["big"]:
            e = per.setdefault(sid, dict(sid=sid, name=name, fam=MF.family(name), n=0, sds2_lb=wt, step_lb=[]))
            e["n"] += 1; e["step_lb"].append(round(wt + d, 4))
        rowsby = collections.defaultdict(collections.Counter); why = {}
        for r in cap["rows"]:
            sid = r.get("piece")
            if not sid:
                continue
            rowsby[sid][r.get("builder")] += 1
            if r.get("standin") and sid not in why:
                why[sid] = r["standin"][:160]
        # per family x builder aggregate (all families)
        agg = collections.defaultdict(lambda: [0.0, 0.0, 0])
        for sid, e in per.items():
            bl = rowsby.get(sid) or {"?": e["n"]}
            bmain = max(bl, key=bl.get)
            a = agg[(e["fam"], bmain)]
            a[0] += sum(e["step_lb"]); a[1] += e["sds2_lb"] * e["n"]; a[2] += e["n"]
        res["fam_builder"] = [dict(fam=f, builder=bb, step_lb=round(v[0], 1), sds2_lb=round(v[1], 1), n=v[2],
                                   ratio=round(v[0] / v[1], 4) if v[1] else None) for (f, bb), v in sorted(agg.items())]
        # families to detail: any family whose ratio is off by > 3 %, plus the flagged ones from argv env
        focus = set(os.environ.get("WD_FAMS", "").split(",")) - {""}
        for f, x in (w.get("by_family") or {}).items():
            if x.get("ratio") is not None and abs(x["ratio"] - 1) > 0.03:
                focus.add(f)
        res["focus"] = sorted(focus)
        det = collections.defaultdict(list)
        for sid, e in per.items():
            if e["fam"] in focus:
                det[e["fam"]].append(e)
        out = {}
        for f, L in det.items():
            L.sort(key=lambda e: -abs(sum(e["step_lb"]) - e["sds2_lb"] * e["n"]))
            rows_ = []
            for k, e in enumerate(L[:300]):
                p = pieces.get(e["sid"], {})
                bl = dict(rowsby.get(e["sid"]) or {})
                rec = dict(sid=e["sid"], name=e["name"], n=e["n"], sds2_lb=round(e["sds2_lb"], 4),
                           step_lb=round(float(np.mean(e["step_lb"])), 4), step_lb_minmax=[min(e["step_lb"]), max(e["step_lb"])],
                           builders=bl, why=why.get(e["sid"], ""), L=p.get("L"), W=p.get("W"), T=p.get("T"), sec=p.get("sec"),
                           kind=PT.kind(p) if p else None, turned=bool(T2.TURNED.match(e["name"])))
                s_ = shapes.get(p.get("sec")) if p else None
                if s_ is not None:
                    rec["shape"] = dict(name=s_.name, d=s_.d, bf=s_.bf, tf=s_.tf, tw=s_.tw, k=s_.k, wt_ft=s_.weight)
                    if p.get("L"):
                        rec["catalog_lb"] = round(s_.weight * p["L"] / 12, 4)
                if p.get("L") and p.get("W") and p.get("T"):
                    rec["LWT_lb"] = round(p["L"] * p["W"] * p["T"] * DENS, 4)
                if k < 60:
                    # the piece's own B-rep (no weight gate) and its decoded holes
                    try:
                        data = open(os.path.join(JOB, "subm", str(e["sid"])), "rb").read()
                        r = brep.parse(data)
                        if r is not None:
                            used = sorted({i for fc in r[1] for i in fc})
                            rec["brep_nv"] = len(r[0]); rec["brep_nf"] = len(r[1])
                            rec["brep_ext"] = [round(float(x), 4) for x in np.ptp(r[0][used], 0)] if used else None
                            sh = brep.solid(*r)
                            rec["brep_closed"] = sh is not None
                            if sh is not None:
                                rec["brep_lb"] = round(vol_lb(sh), 4)
                                H = brep.holes(data)
                                rec["holes"] = len(H)
                                if H and k < 30:
                                    cut = brep.cut_holes(sh, H)
                                    rec["brep_holes_lb"] = round(vol_lb(cut), 4) if cut is not sh else None
                                    rec["hole_dias"] = sorted({round(float(h.get("dia", 0)), 4) for h in H})[:6]
                        else:
                            rec["brep_nv"] = 0
                    except Exception as ex:
                        rec["brep_err"] = f"{type(ex).__name__}: {str(ex)[:80]}"
                    if rec["turned"] or T2.TURNED.match(e["name"] or ""):
                        try:
                            V = T2.mesh_vertices(JOB, e["sid"]); Vt = T2.subm_vertices(JOB, e["sid"])
                            rec["mesh_n"] = 0 if V is None else len(V)
                            rec["mesh_ext"] = None if V is None or not len(V) else [round(float(x), 4) for x in np.ptp(V, 0)]
                            rec["tag_n"] = 0 if Vt is None else len(Vt)
                            rec["tag_ext"] = None if Vt is None or not len(Vt) else [round(float(x), 4) for x in np.ptp(Vt, 0)]
                            sg = T2.turned_local(Vt) if Vt is not None and len(Vt) >= 6 else None
                            sg2 = T2.turned_local(V) if V is not None and len(V) >= 6 else None
                            rec["segs_tag"] = None if not sg else [[round(float(a), 4) for a in s[:3]] + [int(s[3])] for s in sg][:8]
                            rec["segs_mesh"] = None if not sg2 else [[round(float(a), 4) for a in s[:3]] + [int(s[3])] for s in sg2][:8]
                        except Exception as ex:
                            rec["turned_err"] = f"{type(ex).__name__}: {str(ex)[:80]}"
                    if k < 4:
                        s = b[e["sid"] * SLOT:(e["sid"] + 1) * SLOT]
                        rec["slot_hex"] = s.hex()
                rows_.append(rec)
            out[f] = rows_
        res["detail"] = out
        # closed B-reps the weight gate rejected (SDS2 weight vs its own catalog / stock): evidence for recorded-weight outliers
        gate = []
        for (jb, sid), why_ in list(T2.BREP_WHY.items()):
            if "outside 0.6-1.6" not in str(why_) or len(gate) >= 150:
                continue
            p = pieces.get(sid) or {}
            rec = dict(sid=sid, name=p.get("name"), why=why_, sds2_lb=round(p.get("wt", 0), 4), L=p.get("L"), W=p.get("W"), T=p.get("T"),
                       sec=p.get("sec"), kind=PT.kind(p) if p else None)
            s_ = shapes.get(p.get("sec")) if p else None
            if s_ is not None and p.get("L"):
                rec["catalog_lb"] = round(s_.weight * p["L"] / 12, 4); rec["shape"] = s_.name
            if p.get("L") and p.get("W") and p.get("T"):
                rec["LWT_lb"] = round(p["L"] * p["W"] * p["T"] * DENS, 4)
            try:
                data = open(os.path.join(JOB, "subm", str(sid)), "rb").read()
                r = brep.parse(data)
                if r is not None:
                    used = sorted({i for fc in r[1] for i in fc})
                    rec["brep_ext"] = [round(float(x), 4) for x in np.ptp(r[0][used], 0)]
                    sh = brep.solid(*r)
                    if sh is not None:
                        rec["brep_lb"] = round(vol_lb(sh), 4)
                        H = brep.holes(data); rec["holes"] = len(H)
                        if H:
                            cut = brep.cut_holes(sh, H)
                            rec["brep_holes_lb"] = round(vol_lb(cut), 4) if cut is not sh else None
                        rec["extents_match_LWT"] = bool(T2._extents_match(r[0], r[1], p))
            except Exception as ex:
                rec["err"] = f"{type(ex).__name__}"
            gate.append(rec)
        res["gate_rejects"] = gate
        res["gate_rejects_total"] = sum(1 for w_ in T2.BREP_WHY.values() if "outside 0.6-1.6" in str(w_))
    except BaseException as e:
        res["detail_error"] = f"{type(e).__name__}: {e}"; res["detail_tb"] = traceback.format_exc()[-3000:]
res["seconds"] = round(time.time() - t0, 1)
json.dump(res, open(OUT, "w"), default=lambda o: o.item() if hasattr(o, "item") else str(o))
print("done", OUT, res.get("convert_s"), res.get("error"))
