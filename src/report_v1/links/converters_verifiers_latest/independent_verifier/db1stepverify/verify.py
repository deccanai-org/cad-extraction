"""Verify one db1 -> STEP conversion end to end. Stages (each recorded, none silently skipped):
record -> input (+ source-bucket fallback) -> STEP integrity -> OpenCascade geometry -> reproduction from the .db1
-> Tekla-export ground truth -> renders -> VLM -> verdict."""
import os, json, time, hashlib, platform, traceback
import numpy as np
from . import VERSION, config as C
from . import s3io, verdict
from .stepfile import scan


def _versions():
    import importlib.metadata as md
    v = {"db1stepverify": VERSION, "rules": C.RULES_VERSION, "python": platform.python_version()}
    for d in ("cadquery-ocp", "ifcopenshell", "numpy", "scipy"):
        try: v[d] = md.version(d)
        except Exception: v[d] = "unknown"
    return v


def _round(o):
    if isinstance(o, float): return float(f"{o:.{C.FLOAT_DIGITS}g}")
    if isinstance(o, (np.floating,)): return float(f"{float(o):.{C.FLOAT_DIGITS}g}")
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, dict): return {k: _round(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [_round(v) for v in o]
    return o


def verify(sha, work, out_dir, listing_dir=None, do_repro=True, do_truth=True, vlm_mode="queue",
           step_geom_max=C.STEP_GEOM_MAX_BYTES, db1_repro_max=C.DB1_REPRO_MAX_BYTES, keep_files=True, log=print):
    t0 = time.time(); run = {"stages": {}}
    res = dict(sha=sha, step_key=f"{C.STEP_PREFIX}{sha}.stp")
    wd = os.path.join(work, sha[:16]); os.makedirs(wd, exist_ok=True); os.makedirs(out_dir, exist_ok=True)
    stem = sha[:16]

    def stage(name, fn):
        t = time.time()
        try: fn()
        except Exception as e:
            res.setdefault("stage_errors", {})[name] = f"{type(e).__name__}: {e}"[:400]
            run.setdefault("traces", {})[name] = traceback.format_exc()[-2000:]
        run["stages"][name] = round(time.time() - t, 1); log(f"  {stem} {name} {run['stages'][name]}s")

    # 1. record + published object
    def s_record():
        r = s3io.record(sha)
        res["record"] = {k: r.get(k) for k in ("status", "code", "engine", "key", "db1_bytes", "out_bytes", "old_status", "arc_writer", "arc_check",
                                                "excluded_elements", "convert", "markers", "flavour_ok", "readback", "finished", "error")}
        res["record"]["step_parts_reported"] = (r.get("step_stats") or {}).get("parts")
        res["step_object"] = s3io.head(C.BUCKET, res["step_key"])
    stage("record", s_record)
    rec = res.get("record") or {}
    key = rec.get("key")

    # 2. input
    db1_path = os.path.join(wd, "input.db1")
    def s_input():
        inp = res["input"] = dict(key=key)
        h = s3io.head(C.BUCKET, key) if key else dict(error="no key in record")
        inp["in_bucket"] = "error" not in h; inp["bytes"] = h.get("bytes")
        inp["bytes_match_record"] = h.get("bytes") == rec.get("db1_bytes") if inp["in_bucket"] else None
        if key: inp["source_bucket"] = s3io.locate_in_source_bucket(key, listing_dir)
        if inp["in_bucket"]:
            s3io.download(C.BUCKET, key, db1_path)
            inp["sha256"] = s3io.sha256_file(db1_path); inp.update(s3io.db1_facts(db1_path))
    stage("input", s_input)

    # 3. STEP integrity (streamed)
    stp = os.path.join(wd, f"{sha[:16]}.stp")
    names = []
    def s_step():
        s3io.download(C.BUCKET, res["step_key"], stp)
        s = scan(stp); names.extend(s.pop("product_names"))
        s["products"] = len(names)
        import collections
        s["top_names"] = collections.Counter(names).most_common(15)
        res["step"] = s
    stage("step", s_step)

    # 4. geometry
    geo_full = {}
    def s_geom():
        from .geometry import analyze_step, summarize
        if res.get("step", {}).get("bytes", 0) > step_geom_max:
            res["geometry"] = dict(skipped=f"STEP {res['step']['bytes'] / 1e6:.0f} MB > {step_geom_max / 1e6:.0f} MB local limit"); return
        g = analyze_step(stp)
        if g.get("error"): res["geometry"] = dict(error=g["error"]); return
        geo_full.update(g)
        res["geometry"] = dict(summarize(g, names), roots=g["roots"], triangles=int(len(g["tris"])), mesh_complete=g["mesh_complete"])
    stage("geometry", s_geom)
    parts = [dict(p, name=(names[p["part"] - 1] if len(names) == geo_full.get("roots") else None)) for p in geo_full.get("parts", []) if "volume_mm3" in p]

    # 5. reproduction
    from . import match as M
    def s_repro():
        if not do_repro: res["reproduce"] = dict(skipped="disabled"); return
        if not os.path.exists(db1_path): res["reproduce"] = dict(skipped="no input"); return
        if os.path.getsize(db1_path) > db1_repro_max:
            res["reproduce"] = dict(skipped=f".db1 {os.path.getsize(db1_path) / 1e6:.0f} MB > {db1_repro_max / 1e6:.0f} MB local limit"); return
        from .reproduce import run as rr
        r = rr(db1_path, rec.get("engine"), wd, os.path.join(work, "_cache"))
        els = r.pop("elements", None)
        rep = res["reproduce"] = {k: v for k, v in r.items() if k != "stats"}
        rs = r.get("stats") or {}; rc = rec.get("convert") or {}
        rep["decoder_stats"] = {k: rs.get(k) for k in ("members", "written", "sources", "skipped", "cuts_applied", "axis_agreement", "y_vertical_frac_I")}
        rep["same_counts_as_record"] = all(rs.get(k) == rc.get(k) for k in ("members", "written"))
        if els is not None:
            rep["elements"] = len(els)
            if parts:
                m = M.match(parts, els, dist_tol=C.REPRO_CENTROID_TOL_MM, vol_tol=C.REPRO_VOLUME_TOL, near_tol=20.0)
                rep["match"] = m["stats"]
                rep["name_agreement"] = (sum(M.norm_name(parts[i]["name"]) == M.norm_name(els[j]["name"]) for i, j, _, _ in m["pairs"]) / max(1, len(m["pairs"]))) if parts[0].get("name") is not None else None
                rep["unreproduced_examples"] = [dict(part=parts[i]["part"], name=parts[i]["name"], centroid=[round(x, 1) for x in parts[i]["centroid"]]) for i in m["unmatched_a"][:10]]
    stage("reproduce", s_repro)

    # 6. ground truth
    truth_draw = {}
    def s_truth():
        if not do_truth: res["truth"] = dict(status="skipped"); return
        sib = s3io.sibling_ifcs(key) if key else []
        tk = [s for s in sib if s["tekla"] and not s["grid_export"]]
        res["truth"] = dict(candidates=[{k: s[k] for k in ("key", "bytes", "tekla", "grid_export", "same_folder", "schema")} for s in sib[:8]])
        if not tk: res["truth"]["status"] = "none"; return
        if not parts: res["truth"]["status"] = "no_step_geometry"; return
        from .ifcmesh import mesh_ifc_timeout
        best = None; timeouts = []
        for cnd in tk[:2]:
            p = s3io.download(C.BUCKET, cnd["key"], os.path.join(wd, "truth_" + hashlib.sha1(cnd["key"].encode()).hexdigest()[:8] + ".ifc"))
            try:
                els, T, O = mesh_ifc_timeout(p, set(C.TRUTH_EXCLUDED) | {"IfcOpeningElement", "IfcSpace", "IfcGrid", "IfcAnnotation", "IfcVirtualElement", "IfcSite", "IfcBuilding", "IfcBuildingStorey"},
                                             timeout=C.TRUTH_MESH_TIMEOUT_S)
            except TimeoutError as e:
                timeouts.append(dict(ifc=cnd["key"], error=str(e))); continue
            no = M.name_overlap([q["name"] for q in parts if q.get("name")], [e["profile"] or e["name"] for e in els])
            al = M.align(parts, els)
            r = dict(ifc=cnd["key"], ifc_bytes=cnd["bytes"], elements=len(els), name_overlap=no,
                     types={t: sum(1 for e in els if e["type"] == t) for t in sorted({e["type"] for e in els})})
            if al is None:
                r["status"] = "unaligned"
            else:
                m = M.match(parts, els, al["R"], al["t"])
                r.update(status="matched", align=dict(rot_deg=al["rot_deg"], t=[float(x) for x in al["t"]], votes=al["votes"], method=al["method"]), match=m["stats"])
                bt = {}
                for i, j, _, _ in m["pairs"]: bt[els[j]["type"]] = bt.get(els[j]["type"], 0) + 1
                r["recall_by_type"] = {t: round(bt.get(t, 0) / n, 4) for t, n in r["types"].items() if n}
                r["prof_agreement"] = sum(M.norm_name(parts[i]["name"]) == M.norm_name(els[j]["profile"] or "") for i, j, _, _ in m["pairs"]) / max(1, len(m["pairs"]))
                r["near_examples"] = [dict(type=els[j]["type"], profile=els[j]["profile"], step_name=parts[i]["name"], dist_mm=round(d, 1),
                                           vol_ratio=round(vr, 3), centroid=[round(x, 1) for x in els[j]["centroid"]]) for i, j, d, vr in m["near"][:15]]
                r["recall_with_near"] = (m["stats"]["matched"] + m["stats"]["near"]) / max(1, len(els))
                r["displacement"] = M.displacement(parts, els, al["R"], al["t"], m["unmatched_b"])
                inplace = [vr for _, _, d, vr in m["near"] if d <= C.TRUTH_MATCH_DIST_MM]
                r["in_place_other_volume"] = dict(n=len(inplace), median_vol_ratio=float(np.median(inplace)) if inplace else None,
                                                  step_larger=sum(v > 1 for v in inplace))
                r["missing_examples"] = [dict(type=els[j]["type"], name=els[j]["name"], profile=els[j]["profile"], guid=els[j]["guid"],
                                              centroid=[round(x, 1) for x in els[j]["centroid"]]) for j in m["unmatched_b"][:15]]
                r["_m"] = m; r["_draw"] = (els, T, O, al)
            if best is None or (r.get("match", {}).get("recall_b", -1) > best.get("match", {}).get("recall_b", -1)): best = r
        if best is None:
            res["truth"].update(status="timeout", timeouts=timeouts); return
        if timeouts: best["timeouts"] = timeouts
        d = best.pop("_draw", None); m = best.pop("_m", None)
        if d is not None: truth_draw.update(d=d, m=m)
        res["truth"].update(best)
    stage("truth", s_truth)

    # 7. renders
    images = []
    def s_render():
        if not geo_full.get("parts"): return
        from . import render as Rd
        cols = Rd.part_colors(names if len(names) == geo_full["roots"] else [""] * geo_full["roots"])
        cols = np.vstack([cols, Rd.COL_MEMBER])            # owner -1 (unknown) -> default colour
        P, N, own = Rd.sample(geo_full["tris"], geo_full["tri_part"])
        col = cols[own]; core = Rd.core_frame(P)
        pan = [("iso (core)", Rd.view(P, N, col, *Rd.VIEWS["iso"], frame=core)),
               ("plan (core)", Rd.view(P, N, col, *Rd.VIEWS["plan"], frame=core)),
               ("front elevation (core)", Rd.view(P, N, col, *Rd.VIEWS["front"], frame=core)),
               ("iso - FULL extent", Rd.view(P, N, col, *Rd.VIEWS["iso"]))]
        g = res.get("geometry", {})
        title = f"{sha[:16]}  Xsteel {rec.get('engine')}  {g.get('parts')} parts  extent {[round(x / 1000, 1) for x in g.get('extent_mm', [0, 0, 0])]} m"
        images.append(Rd.panel_sheet(pan, 2, title, os.path.join(out_dir, stem + "_step.png"),
                                     footer=f"{rec.get('key', '')[-150:]}"))
        if truth_draw.get("d"):
            els, T, O, al = truth_draw["d"]; m = truth_draw["m"]
            Rinv = al["R"].T; Tl = (T - al["t"]) @ Rinv.T               # export -> STEP frame
            ix = lambda L: np.array(L, dtype=np.int64)
            stB = np.zeros(len(els), np.int64); stB[ix([j for _, j, _, _ in m["pairs"]])] = 1; stB[ix([j for _, j, _, _ in m["near"]])] = 2
            okA = np.zeros(geo_full["roots"] + 1, bool)
            for i, _, _, _ in m["pairs"]: okA[parts[i]["part"] - 1] = True
            PB, NB, oB = Rd.sample(Tl, O, n_points=C.RENDER_POINTS // 2)
            cB = np.array([Rd.COL_MISS, Rd.COL_OK, Rd.COL_NEAR])[stB[oB]]
            cA = np.where(okA[own][:, None], Rd.COL_OK, Rd.COL_MEMBER)
            fr = Rd.core_frame(np.vstack([P[::7], PB[::7]]))
            pan2 = [("STEP iso (green = matched)", Rd.view(P, N, cA, *Rd.VIEWS["iso"], frame=fr)),
                    ("STEP plan", Rd.view(P, N, cA, *Rd.VIEWS["plan"], frame=fr)),
                    ("Tekla export iso (green = in STEP, yellow = in place but volume differs, red = missing)", Rd.view(PB, NB, cB, *Rd.VIEWS["iso"], frame=fr)),
                    ("Tekla export plan", Rd.view(PB, NB, cB, *Rd.VIEWS["plan"], frame=fr))]
            mt = res["truth"]["match"]
            images.append(Rd.panel_sheet(pan2, 2, f"{sha[:16]} vs Tekla export ({mt['b']} elements, STEP has {mt['a']} parts): "
                                                  f"{mt['recall_b']:.1%} found, {mt['near'] / max(1, mt['b']):.1%} in place with other volume",
                                         os.path.join(out_dir, stem + "_vs_tekla.png"), footer=res["truth"]["ifc"][-150:]))
        res["renders"] = [os.path.basename(p) for p in images]
    stage("render", s_render)

    # 8. VLM
    def s_vlm():
        from . import vlm
        if not images or vlm_mode == "none": return
        g = res.get("geometry", {})
        facts = dict(parts=g.get("parts"), extent_m=[round(x / 1000, 1) for x in g.get("extent_mm", [0, 0, 0])], strays=g.get("stray_parts"),
                     tekla_recall=(res.get("truth", {}).get("match") or {}).get("recall_b"))
        ans_path = os.path.join(out_dir, stem + "_vlm.json")
        if os.path.exists(ans_path):
            res["vlm"] = vlm.validate(json.load(open(ans_path)))
        elif vlm_mode == "api":
            res["vlm"] = vlm.judge_api([os.path.join(out_dir, os.path.basename(p)) for p in images], facts, len(images) > 1)
            json.dump(res["vlm"], open(ans_path, "w"), indent=1)
        else:
            vlm.write_queue(out_dir, stem, [os.path.join(out_dir, os.path.basename(p)) for p in images], facts, len(images) > 1)
            res["vlm"] = dict(queued=True)
    stage("vlm", s_vlm)

    verdict.decide(res)
    res = _round(res)
    res["versions"] = _versions()
    blob = json.dumps({k: v for k, v in res.items() if k not in ("versions", "vlm", "renders")}, sort_keys=True, default=str).encode()
    res["result_digest"] = hashlib.sha256(blob).hexdigest()
    run.update(t_total_s=round(time.time() - t0, 1), host=platform.node(), work_dir=wd)
    json.dump({"result": res, "run": run}, open(os.path.join(out_dir, stem + ".json"), "w"), indent=1, sort_keys=True, default=str)
    if not keep_files:
        for f in os.listdir(wd):
            try: os.remove(os.path.join(wd, f))
            except OSError: pass
    return res, run


def reverdict(json_path):
    """re-apply the rules (e.g. after a VLM answer arrives) without redoing the heavy stages"""
    d = json.load(open(json_path)); res = d["result"]
    from . import vlm
    ans = json_path[:-5] + "_vlm.json"
    if os.path.exists(ans): res["vlm"] = vlm.validate(json.load(open(ans)))
    verdict.decide(res)
    json.dump(d, open(json_path, "w"), indent=1, sort_keys=True, default=str)
    return res
