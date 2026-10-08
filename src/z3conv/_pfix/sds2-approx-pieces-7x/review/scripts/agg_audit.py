"""agg_audit.py AUDITDIR -> compact JSON: per job base/cand/v556 summaries, identity / negwt / repair details, coverage stats."""
import sys, os, json, glob, collections
A = sys.argv[1]; out = {}
for f in sorted(glob.glob(os.path.join(A, "cand__*.json"))):
    job = os.path.basename(f)[6:-5]
    def ld(v):
        p = os.path.join(A, f"{v}__{job}.json")
        return json.load(open(p)) if os.path.exists(p) else None
    b, c, v6 = ld("base553"), ld("cand"), ld("v556")
    r = dict(base=b and {k: b["summary"][k] for k in ("pieces_n", "placements", "exact_pieces", "exact_placements", "wall")})
    if c:
        s = c["summary"]; P = c["pieces"]; BP = b["pieces"] if b else {}
        r["cand"] = {k: s.get(k) for k in ("exact_pieces", "exact_placements", "wall", "lost_pieces", "lost_placements", "changed_exact",
                                           "new_pieces", "new_placements", "fabricated_suspects", "coverage_errors", "new_invalid",
                                           "new_by", "calibration")}
        new = [k for k, d in P.items() if d["exact"] and not BP.get(k, {}).get("exact")]
        cov = [P[k].get("coverage") or {} for k in new]
        fr = [x.get("uncovered_frac") for x in cov if x.get("uncovered_frac") is not None]
        r["cov_stats"] = dict(n=len(fr), max=max(fr) if fr else None, n_gt_1e4=sum(1 for x in fr if x > 1e-4),
                              n_gt_1e6=sum(1 for x in fr if x > 1e-6))
        r["cov_worst"] = sorted([dict(piece=k, name=P[k]["name"], frac=(P[k].get("coverage") or {}).get("uncovered_frac"),
                                      unc=(P[k].get("coverage") or {}).get("uncovered_area"), repair=P[k].get("repair"),
                                      identity=P[k].get("identity"), ex=(P[k].get("coverage") or {}).get("uncovered_examples", [])[:3])
                                 for k in new], key=lambda d: -(d["frac"] or 0))[:6]
        r["identity"] = [dict(piece=k, name=d["name"], kind=d["kind"], n=d["n_inst"], wt=d["wt"], L=d["L"], W=d["W"], T=d["T"],
                              vol=round(d.get("vol", 0), 2), ratio=round(d.get("vol", 0) * 0.2836 / d["wt"], 3) if d["wt"] else None,
                              bbox=d.get("bbox"), note=d["identity"]) for k, d in P.items() if d.get("identity")]
        r["negwt"] = [dict(piece=k, name=d["name"], n=d["n_inst"], wt=d["wt"], ratio=d["negwt"]) for k, d in P.items() if d.get("negwt")]
        r["repair_by"] = dict(collections.Counter(d["repair"] for k, d in P.items() if d.get("repair") and d["exact"]))
        r["new_ratio_dist"] = sorted(round(P[k].get("vol", 0) * 0.2836 / P[k]["wt"], 3) for k in new if P[k]["wt"] > 0)
        r["still_rejected"] = dict(collections.Counter((d.get("why") or "?")[:60] for d in P.values() if not d["exact"]))
    if v6:
        s = v6["summary"]; P6 = v6["pieces"]; BP = b["pieces"] if b else {}
        lost = s.get("lost_pieces", [])
        r["v556"] = dict(exact_pieces=s["exact_pieces"], exact_placements=s["exact_placements"], lost_placements=s.get("lost_placements"),
                         lost=[dict(piece=k, name=BP[k]["name"], n=BP[k]["n_inst"], why=P6.get(k, {}).get("why"),
                                    open_surface=P6.get(k, {}).get("open_surface")) for k in lost][:20],
                         new_placements=s.get("new_placements"), fabricated_suspects=s.get("fabricated_suspects"))
        if c:
            # pieces exact in the patch but not in v5.5.6, and vice versa
            r["cand_vs_v556"] = dict(
                cand_only=sum(c["pieces"][k]["n_inst"] for k in c["pieces"] if c["pieces"][k]["exact"] and not P6.get(k, {}).get("exact")),
                v556_only=sum(P6[k]["n_inst"] for k in P6 if P6[k]["exact"] and not c["pieces"].get(k, {}).get("exact")))
    out[job] = r
json.dump(out, open(sys.argv[2], "w"), indent=1, default=str)
for j, r in out.items():
    c = r.get("cand") or {}
    print(j[:40], "base", r["base"] and (r["base"]["exact_placements"], r["base"]["placements"]), "cand+", c.get("new_placements"),
          "lost", c.get("lost_placements"), "chg", len(c.get("changed_exact") or []), "fab", c.get("fabricated_suspects"),
          "cov", r.get("cov_stats"), "inv", c.get("new_invalid"), "v556", r.get("v556") and (r["v556"]["new_placements"], r["v556"]["lost_placements"]))
