"""Can this SDS2 job be converted? Runs the real decoders on a job folder and scores them against the job's own data
(no IFC needed). Prints one JSON line.

  sections : rolled pieces whose section index (subm_idx) resolves to a job_mtrl name equal to the piece's own name
  members  : structural members with a section; beams on W/C/M/S shapes; columns vertical
  pieces   : placed pieces whose built solid volume matches the piece weight stored in subm_idx (within 10%)
verdict: stage2 (all pass), stage1 (members pass, pieces don't), no (members fail or a reader raises)
  members pass: >=80% of structural members have a section, and >=90% of sections match piece names (or, if the
                piece table can't be read, >=50% of beams resolve to W/C/M/S/HP/WT shapes)
  pieces pass : >=80% of sampled members have placed pieces and >=75% of checked pieces match their weight

usage: python preflight.py <job_dir> [n_members_sampled]
"""
import os, sys, re, json, random, collections, traceback
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
STRUCT = {"BEAM", "COLUMN", "VERTICAL BRACE", "HORIZONTAL BRACE", "JOIST"}


def preflight(job, n_sample=150):
    import sds2job as S
    out = {"job": job, "version": S.read_version(job)}
    try:
        shapes = S.read_shapes(job)
        out["shapes"] = len(shapes)
        L = S.calibrate(job, shapes)
        mems, _ = S.read_members(job, L)
    except Exception as e:
        out.update(verdict="no", error=f"members: {type(e).__name__}: {e}"[:300]); return out
    st = [m for m in mems if m.type in STRUCT]
    beams = [m for m in mems if m.type == "BEAM"]; cols = [m for m in mems if m.type == "COLUMN"]
    out["members"] = len(mems); out["structural"] = len(st)
    out["with_section"] = round(np.mean([m.section is not None for m in st]), 3) if st else None
    out["beams_on_wc"] = round(np.mean([bool(m.section) and m.section.family in ("W", "C", "MC", "M", "S", "HP", "WT")
                                        for m in beams]), 3) if beams else None
    def vertical(m):
        d = np.subtract(m.p2, m.p1); n = np.linalg.norm(d)
        return n > 0 and abs(d[2]) > 0.99 * n
    out["cols_vertical"] = round(np.mean([vertical(m) for m in cols]), 3) if cols else None
    if L.get("fw", 8) == 8:                       # member section vs the member's own main-piece name
        idx = open(os.path.join(job, "mem", "mem_idx"), "rb").read()
        ids = sorted(int(n) for n in os.listdir(os.path.join(job, "mem")) if n.isdigit())
        ag = S._main_piece_agreement(job, idx, L["slot"], L["type"], ids, shapes, [L["sec"]])
        out["sections_vs_main_piece"] = round(ag[L["sec"]], 3) if ag else None

    # pieces
    try:
        from piece_table import read_pieces, kind
        from instances import material_instances, subm_vertices
        import to_step2 as T2
        from OCP.GProp import GProp_GProps
        from OCP.BRepGProp import BRepGProp
        P = read_pieces(job)
        pairs = [(p["sec"], p["name"]) for p in P.values() if kind(p) == "rolled"]
        ok = [shapes.get(s) is not None and shapes[s].name == n for s, n in pairs]
        out["pieces"] = len(P)
        out["sections_match"] = round(np.mean(ok), 3) if ok else None
        random.seed(0)
        samp = random.sample(st, min(n_sample, len(st)))
        has_inst, ratios = [], []
        for m in samp:
            inst = material_instances(job, m.id, P)[1]
            has_inst.append(bool(inst) or m.type == "JOIST")
            for sid, M, o in inst[:4]:
                p = P[sid]; k = kind(p)
                if p["wt"] <= 0 or k == "other": continue
                V = subm_vertices(job, sid)
                if V is None or len(V) < 4: continue
                loc = T2.plate_local(V, p) if k == "plate" else (T2.rolled_local(V, shapes[p["sec"]], p["L"]) if p["sec"] in shapes else None)
                sh = loc and T2.prism(loc[0], loc[1], loc[2] if len(loc) > 2 else [])
                if sh is None: ratios.append(0.0); continue
                g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g)
                ratios.append(abs(g.Mass()) / 25.4 ** 3 * 0.2836 / p["wt"])
        out["members_with_pieces"] = round(np.mean(has_inst), 3) if has_inst else None
        out["piece_weight_within10"] = round(float(np.mean(np.abs(np.array(ratios) - 1) < 0.1)), 3) if ratios else None
        out["pieces_checked"] = len(ratios)
    except Exception as e:
        out["piece_error"] = f"{type(e).__name__}: {e}"[:300]

    out["verdict"] = verdict(out)
    return out


def verdict(out):
    """beams_on_wc is informational when pieces confirm the sections: metal-building jobs frame with plate girders /
    purlins and are fine.
    cols_vertical is informational too (towers and canopies have raked columns). sections_match checks the member
    section index only when the piece table itself was readable; an unreadable piece table (new subm_idx layout,
    7.5xx/7.6xx) caps the job at stage1 and falls back to "beams resolve to real shapes" for the member check."""
    if out.get("error"):
        return "no"
    sm = out.get("sections_match")
    piece_table_ok = sm is not None and sm > 0.2
    members_ok = (out.get("structural") or 0) > 0 and (out.get("with_section") or 0) >= 0.8 \
        and ((sm >= 0.9) if piece_table_ok else (out.get("beams_on_wc") or 0) >= 0.5)
    pieces_ok = members_ok and piece_table_ok and sm >= 0.9 and (out.get("members_with_pieces") or 0) >= 0.8 \
        and (out.get("piece_weight_within10") or 0) >= 0.75
    return "stage2" if pieces_ok else ("stage1" if members_ok else "no")


if __name__ == "__main__":
    try:
        r = preflight(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 150)
    except Exception as e:
        r = {"job": sys.argv[1], "verdict": "no", "error": traceback.format_exc()[-300:]}
    print(json.dumps(r))
