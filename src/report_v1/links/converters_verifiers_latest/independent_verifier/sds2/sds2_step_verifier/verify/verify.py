"""Verify an SDS2 -> STEP conversion.

usage:
  python verify.py --job <SDS2 job dir> --step <out.step> [--manifest <csv>] [--gt <folder>]
                   [--ifc f.ifc] [--kss a.kss ...] [--nc1-dir dir] [--selftest] [--out report_prefix]

Verdict:
  overall  = FAIL if any check FAILs, else WARN if any WARNs, else PASS  (NA never counts as PASS)
  evidence = 'external' if an E-check (IFC / KISS / NC1) passed, 'mass' if only M1 passed, else 'internal'
Self-test (--selftest): applies deliberate defects to a copy of the solid table (shift, unit error, dropped
solids, wrong sections, rotated webs, top-of-steel error, duplicates, mirror, scattered pieces) and records which
checks catch each one. A defect nobody catches is reported as a blind spot.
"""
import os, sys, json, glob, math, copy, random, struct, argparse, collections, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "decode"))
import checks as C
from steptable import read_step
import groundtruth as GT
import tiers


class Ctx:
    pass


def build_ctx(a):
    from sds2job import read_members, read_version, read_shapes
    ctx = Ctx()
    ctx.job = a.job
    ctx.version = read_version(a.job)
    try:
        ctx.shapes = read_shapes(a.job)
    except Exception as ex:           # EC-06: unsupported job_mtrl layout
        ctx.shapes = {}; ctx.shape_error = str(ex)
    try:
        ctx.members, ctx.layout = read_members(a.job) if ctx.shapes else ([], {})
    except Exception as ex:
        ctx.members, ctx.layout = [], {}; ctx.member_error = str(ex)
    ctx.member_by_id = {m.id: m for m in ctx.members}
    # raw roll values straight from mem_idx (the reader sanitises them, so read again) - EC-14
    ctx.raw_roll_bad_share = 0.0
    if ctx.layout:
        idx = open(os.path.join(a.job, "mem", "mem_idx"), "rb").read()
        bad = n = 0
        for m in ctx.members:
            if m.type not in C.STRUCTURAL: continue
            o = m.id * ctx.layout["slot"] + ctx.layout["roll"]
            v = struct.unpack(">d", idx[o:o + 8])[0]
            n += 1; bad += (not math.isfinite(v)) or abs(v) > 7
        ctx.raw_roll_bad_share = bad / n if n else 0.0
    st = [m for m in ctx.members if m.type in C.STRUCTURAL]
    pts = np.array([p for m in st for p in (m.p1, m.p2)]) if st else np.zeros((2, 3))
    ctx.decoded_extent = (pts.min(0), pts.max(0))
    return ctx


def attach_step(ctx, a):
    tab = read_step(a.step)
    ctx.step_path = a.step
    # bolts belong to no SDS2 member or piece: kept aside (counted for the tier), not in the member/piece checks
    ctx.bolts = [t for t in tab["solids"] if t["stage"] == "bolt"]
    ctx.table = [t for t in tab["solids"] if t["stage"] != "bolt"]; ctx.step_unit = tab["unit"]
    ctx.assembly_mode = any(t.get("in_assembly") for t in ctx.table)
    stages = collections.Counter(t["stage"] for t in ctx.table)
    ctx.stage = stages.most_common(1)[0][0] if stages else "unknown"
    # manifest
    man = a.manifest or next((p for p in (os.path.splitext(a.step)[0] + "_members.csv", os.path.splitext(a.step)[0] + "_pieces.csv") if os.path.exists(p)), None)
    ctx.manifest_count = None
    if man:
        import csv
        rows = list(csv.DictReader(open(man)))
        ctx.manifest_count = sum(1 for r in rows if r.get("solid", "1") == "1")
        ctx.manifest_rows = rows
    skipped = os.path.splitext(a.step)[0] + "_skipped.csv"             # v4 converter: unbuilt pieces + reason
    if os.path.exists(skipped):
        import csv
        ctx.skipped_rows = list(csv.DictReader(open(skipped, encoding="utf-8")))
    # part tags may sit in the manifest instead of the solid name (fix spec: "mark it approx in the manifest")
    ctx.manifest_tagged = tiers.merge_manifest_tags(ctx)
    # expected weights
    def member_weight(t):
        m = ctx.member_by_id.get(t["member_id"])
        if not m or not m.section or m.section.weight <= 0: return None
        return m.section.weight * np.linalg.norm(np.subtract(m.p2, m.p1)) / 12.0
    if ctx.stage == "piece":
        from piece_table import read_pieces
        pieces = read_pieces(ctx.job)
        # member envelopes (piece 0: members with no fabricated pieces, e.g. joists) weigh as their member
        ctx.expected_weight = lambda t: member_weight(t) if t["piece_id"] == 0 else pieces.get(t["piece_id"], {}).get("wt")
        ctx.mass_tol, ctx.mass_median_band, ctx.mass_pass_share = 0.15, (0.85, 1.15), 0.75
    else:
        ctx.expected_weight = member_weight
        ctx.mass_tol, ctx.mass_median_band, ctx.mass_pass_share = 0.10, (0.90, 1.06), 0.90
        ctx.mass_warn_share = 0.85      # below this a wrong-section defect is a FAIL (run-2: p10 of clean jobs = 0.97)
    ctx.family_of = lambda t: (GT.canon(t["section"]).rstrip("0123456789X./") or "?")[:4]
    ctx.centers = lambda: [t["center"] for t in ctx.table]
    ctx.ifc_alignment = None


def attach_gt(ctx, a):
    files = dict(ifc=[], kss=[], nc1=[])
    if a.gt:
        files = GT.discover(a.gt)
    if a.ifc: files["ifc"] = [a.ifc]
    if a.kss: files["kss"] = a.kss
    if a.nc1_dir: files["nc1"] = sorted(glob.glob(os.path.join(a.nc1_dir, "**", "*.nc1"), recursive=True))
    ctx.gt_files = {k: len(v) for k, v in files.items()}
    ctx.ifc = GT.read_ifc(files["ifc"][0]) if files["ifc"] else None
    ctx.kiss = GT.read_kiss(files["kss"]) if files["kss"] else []
    ctx.nc1 = GT.read_nc1(files["nc1"]) if files["nc1"] else []


def run_checks(ctx, fns):
    out = []
    for f in fns:
        try:
            r = f(ctx)
        except Exception as ex:
            r = C.Result(f.__name__.split("_")[0].upper(), f.__name__, "FAIL", {}, f"check crashed: {type(ex).__name__}: {ex}")
        out.append(r)
    return out


# ------------------------------------------------------------------ self-test mutations
def _mut(name, table, rng, ctx):
    T = copy.deepcopy(table)
    def move(t, d):
        for k in ("lo", "hi", "center"): t[k] = [v + dv for v, dv in zip(t[k], d)]
    if name == "shift 10% of solids by 6 in":
        for t in rng.sample(T, max(1, len(T) // 10)): move(t, (6, 0, 0))
    elif name == "unit error (inches written as mm)":
        for t in T:
            for k in ("lo", "hi", "center", "obb"): t[k] = [v / 25.4 for v in t[k]]
            t["volume"] /= 25.4 ** 3
    elif name == "drop 15% of solids":
        T = rng.sample(T, int(len(T) * 0.85))
    elif name == "wrong section on 20% (x1.6 area)":
        for t in rng.sample(T, max(1, len(T) // 5)):
            t["volume"] *= 1.6
            c = np.array(t["center"]); ax = int(np.argmax(np.array(t["hi"]) - t["lo"]))
            for k in range(3):
                if k != ax: h = (t["hi"][k] - t["lo"][k]) / 2 * 1.26; t["lo"][k], t["hi"][k] = c[k] - h, c[k] + h
    elif name == "web rotated 90 deg on 30% of beams":
        beams = [t for t in T if t["member_type"] == "BEAM"]
        for t in rng.sample(beams, max(1, len(beams) * 3 // 10)) if beams else []:
            c = np.array(t["center"]); ext = np.array(t["hi"]) - t["lo"]; ax = int(np.argmax(ext))
            o = [k for k in range(3) if k != ax]
            ext[o[0]], ext[o[1]] = ext[o[1]], ext[o[0]]
            t["lo"] = (c - ext / 2).tolist(); t["hi"] = (c + ext / 2).tolist()
    elif name == "beams centred instead of top-of-steel":
        for t in T:
            if t["member_type"] == "BEAM":
                h = (t["hi"][2] - t["lo"][2]) / 2; move(t, (0, 0, h))
    elif name == "5% duplicated solids":
        T = T + copy.deepcopy(rng.sample(T, max(1, len(T) // 20)))
    elif name == "model mirrored in x":
        xs = [t["center"][0] for t in T]; cx = (min(xs) + max(xs)) / 2
        for t in T:
            lo, hi = t["lo"][0], t["hi"][0]; t["lo"][0], t["hi"][0] = 2 * cx - hi, 2 * cx - lo; t["center"][0] = 2 * cx - t["center"][0]
    elif name == "20% of pieces scattered 12 in":
        pieces = [t for t in T if t["stage"] == "piece"] or T
        for t in rng.sample(pieces, max(1, len(pieces) // 5)):
            d = np.array([rng.uniform(-1, 1) for _ in range(3)]); d = d / np.linalg.norm(d) * 12; move(t, d)
    return T


MUTATIONS = ["shift 10% of solids by 6 in", "unit error (inches written as mm)", "drop 15% of solids",
             "wrong section on 20% (x1.6 area)", "web rotated 90 deg on 30% of beams", "beams centred instead of top-of-steel",
             "5% duplicated solids", "model mirrored in x", "20% of pieces scattered 12 in"]
LEVEL = {"NA": 0, "PASS": 1, "WARN": 2, "FAIL": 3}


def selftest(ctx, base):
    rng = random.Random(7)
    base_by = {r.id: r.status for r in base}
    table0, align0 = ctx.table, ctx.ifc_alignment
    rows = []
    for name in MUTATIONS:
        ctx.table = _mut(name, table0, rng, ctx)
        ctx.ifc_alignment = None if name in ("unit error (inches written as mm)", "model mirrored in x") else align0
        res = run_checks(ctx, C.TABLE_CHECKS)
        caught = [f"{r.id}:{base_by.get(r.id)}->{r.status}" for r in res if LEVEL[r.status] > LEVEL.get(base_by.get(r.id), 0) and LEVEL[r.status] >= 2]
        fails = [r.id for r in res if r.status == "FAIL" and base_by.get(r.id) != "FAIL"]
        rows.append(dict(mutation=name, detected=bool(caught), to_fail=bool(fails), caught_by=caught))
    ctx.table, ctx.ifc_alignment = table0, align0
    return rows


# ------------------------------------------------------------------ report
def fmt(v):
    if isinstance(v, float): return f"{v:.4g}"
    if isinstance(v, dict): return ", ".join(f"{k}={fmt(x)}" for k, x in list(v.items())[:8])
    if isinstance(v, (list, tuple)): return "[" + ", ".join(fmt(x) for x in v[:6]) + (", ..." if len(v) > 6 else "") + "]"
    return str(v)


# Member-decoder checks: they judge the verifier's own reading of the member index (work points, section field).
# Stage-2 geometry comes from piece placements, so for stage-2 files these are reported, not verdict-making.
MEMBER_DECODE = {"D3", "D4", "D5", "D6"}


def verdict(results, has_step, stage=None):
    """One answer per file:
    CANNOT VERIFY  the job's layout could not be decoded, so there is nothing trustworthy to compare against
    INCORRECT      something in the STEP is wrong (geometry, sections, units, validity, disagreement with ground truth)
    INCOMPLETE     the STEP is sound but items that should be there are missing (C1)
    CORRECT        everything checked passed (warnings, if any, are listed)
    READY / NOT CONVERTIBLE  pre-conversion gate only (no STEP given)"""
    st = {r.id: r.status for r in results}
    c1 = next((r for r in results if r.id == "C1"), None)
    pieces_decoded = stage == "piece" and c1 is not None and (c1.metrics.get("expected_pieces") or 0) > 0
    if (st.get("D1") == "FAIL" or st.get("D2") == "FAIL") and not pieces_decoded:
        return "CANNOT VERIFY" if has_step else "NOT CONVERTIBLE"
    if not has_step:
        return "NOT CONVERTIBLE" if any(v == "FAIL" for v in st.values()) else "READY TO CONVERT"
    skip = {"C1"} | (MEMBER_DECODE | {"D1", "D2"} if stage == "piece" else set())
    hard = [k for k, v in st.items() if v == "FAIL" and k not in skip]
    if hard:
        return "INCORRECT"
    if st.get("C1") in ("FAIL", "WARN"):
        return "INCOMPLETE"
    return "CORRECT" if not any(v == "WARN" for v in st.values()) else "CORRECT (with warnings)"


def write_report(prefix, ctx, results, st_rows, meta):
    overall = C.worst([r.status for r in results])
    e_pass = [r.id for r in results if r.id.startswith("E") and r.status == "PASS"]
    evidence = "external" if e_pass else ("mass" if any(r.id == "M1" and r.status == "PASS" for r in results) else "internal")
    blind = [s["mutation"] for s in st_rows if not s["detected"]] if st_rows else None
    v = verdict(results, bool(meta.get("step")), ctx.stage)
    why = [f"{r.id} {r.status}: {r.reason}" for r in results if r.status in ("FAIL", "WARN") and r.reason]
    tier = tiers.tier_for(ctx, results, v, evidence)
    out = dict(meta, verdict=v, verdict_reasons=why, tier=tier, overall=overall, evidence=evidence, external_checks_passed=e_pass,
               checks=[r.__dict__ for r in results], selftest=st_rows, selftest_blind_spots=blind)
    json.dump(out, open(prefix + ".json", "w"), indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
    if getattr(ctx, "missing_items", None):
        import csv
        with open(prefix + "_missing.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(ctx.missing_items[0].keys())); w.writeheader(); w.writerows(ctx.missing_items)
    L = [f"# SDS2 -> STEP verification: {os.path.basename(meta['step']) or os.path.basename(meta['job'])}", "",
         f"## Verdict: {v}", ""] + [f"- {x}" for x in why] + ["",
         f"## Corpus tier: {tier['tier']}" + (f" ({tier['tier_confidence']})" if tier.get("tier_confidence") else ""), ""] + [f"- {x}" for x in tier["tier_reasons"]] + ["",
         f"Overall check status: {overall} | evidence: {evidence} | stage: {ctx.stage} | version {ctx.version} | solids {len(ctx.table):,}", "",
         f"Ground truth found: IFC {ctx.gt_files.get('ifc', 0)}, KISS {ctx.gt_files.get('kss', 0)}, NC1 {ctx.gt_files.get('nc1', 0)}", "",
         "| check | status | key metrics | reason |", "|---|---|---|---|"]
    for r in results:
        L.append(f"| {r.id} {r.title} | **{r.status}** | {fmt(r.metrics)} | {r.reason} |")
    if st_rows:
        L += ["", "## Self-test (deliberate defects)", "", "| defect | detected | escalates to FAIL | caught by |", "|---|---|---|---|"]
        for s in st_rows:
            L.append(f"| {s['mutation']} | {'yes' if s['detected'] else '**NO**'} | {'yes' if s['to_fail'] else 'no'} | {', '.join(s['caught_by'])} |")
        L += ["", f"Blind spots: {', '.join(blind) if blind else 'none'}"]
    open(prefix + ".md", "w", encoding="utf-8").write("\n".join(L) + "\n")
    return v, overall, evidence, blind


def dedup_copy(step, removals, out_dir, n_before):
    """Write the de-duplicated copy and read it back: it must hold exactly n_before - removed solids, all valid."""
    import dedup
    try:
        out, n = dedup.write_clean(step, removals, out_dir)
        back = read_step(out, use_cache=False)["solids"]
        ok = len(back) == n_before - n and all(t["valid"] for t in back)
        return dict(file=out, removed=n, solids_before=n_before, solids_after=len(back), readback_ok=ok)
    except Exception as ex:
        return dict(file=None, removed=0, error=f"{type(ex).__name__}: {ex}", readback_ok=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True); ap.add_argument("--step")
    ap.add_argument("--manifest"); ap.add_argument("--gt"); ap.add_argument("--ifc"); ap.add_argument("--kss", nargs="*")
    ap.add_argument("--nc1-dir"); ap.add_argument("--selftest", action="store_true"); ap.add_argument("--out")
    ap.add_argument("--dedup-out", help="folder for a copy of the STEP without the converter's exact duplicate solids "
                                         "(written only for tiered files that have some; the original is never changed)")
    a = ap.parse_args()
    t0 = time.time()
    ctx = build_ctx(a)
    dup_remove = []
    if a.step:
        attach_step(ctx, a)
        attach_gt(ctx, a)
        results = run_checks(ctx, C.ALL)
        dup_remove = list(getattr(ctx, "dup_remove", []))      # before the self-test re-runs G4 on mutated tables
    else:                       # pre-conversion gate: decode-sanity checks only
        ctx.stage, ctx.table, ctx.gt_files = "pre-conversion", [], {}
        results = run_checks(ctx, [C.d1_version_gate, C.d2_shape_table, C.d3_section_field, C.d4_geometry_fields, C.d5_outliers, C.d6_section_crosscheck])
    st_rows = selftest(ctx, results) if (a.selftest and a.step) else None
    prefix = a.out or (os.path.splitext(a.step)[0] + "_verify" if a.step else os.path.join(HERE, "..", "out", os.path.basename(a.job.rstrip("\\/")) + "_precheck"))
    meta = dict(job=a.job, step=a.step or '', version=ctx.version, stage=ctx.stage, seconds=round(time.time() - t0, 1))
    v, overall, evidence, blind = write_report(prefix, ctx, results, st_rows, meta)
    rep = json.load(open(prefix + ".json"))
    if a.dedup_out and dup_remove and rep["tier"]["tier"] != "EXCLUDED":
        rep["dedup"] = dedup_copy(a.step, dup_remove, a.dedup_out, len(ctx.table) + len(ctx.bolts))
        json.dump(rep, open(prefix + ".json", "w"), indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
        print(f"DEDUP {rep['dedup']}")
    for r in results:
        print(f"{r.id:3s} {r.status:4s}  {r.title}: {fmt(r.metrics)}  {r.reason}")
    if st_rows:
        for s in st_rows: print(f"  selftest {'OK ' if s['detected'] else 'MISS'} {s['mutation']}: {s['caught_by']}")
    print(f"OVERALL {overall} (evidence: {evidence}); report -> {prefix}.md")
    print(f"VERDICT {v}")
    t = json.load(open(prefix + ".json"))["tier"]
    print(f"TIER {t['tier']} {t.get('tier_confidence') or ''}" + (f"  ({'; '.join(t['tier_reasons'])})" if t["tier_reasons"] else ""))


if __name__ == "__main__":
    main()

