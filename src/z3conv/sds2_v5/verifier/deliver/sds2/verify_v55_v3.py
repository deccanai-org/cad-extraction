"""Run sds2_step_verifier v1.3.3 on sds2-step-pipeline v5.5.x output (thin adapter; the verifier is not modified).

usage: python verify_v55.py --verifier <sds2_step_verifier dir> [--no-decoder-fix] [--no-policy] <verify.py args ...>
       e.g. --job <SDS2 job dir> --step <x_stage2.step> [--gt <folder>] [--out <prefix>]

What it adapts (format; the verifier's checks and thresholds are its own, except where the grading policy (6) says):
  1. Names. v5.x tags stand-ins after the parentheses, "... (piece 12, inst 3) [approx: <why>]", plus
     "[reference: ...]" (imported reference models) and "[derived: ...]" (part names only). v1.3.3 expects tags inside
     the parentheses, so every such solid parsed as 'unknown' (S1/S3 FAIL, tags lost). The bracket is stripped and
     mapped to the verifier's tags: [approx: ...] -> approx (bolts: their nominal name already gives bolt_guessed),
     [reference: ...] -> reference (no tier flag). "(joist stand-in)" (v5.5 open-web joist model for a member with no
     pieces) is read like v4's "(member envelope)": piece 0, member_envelope (-> joist_envelope on joists).
  2. Manifest. v5.x _pieces.csv names every non-exact row in its `standin` column and has more `builder` values
     than v4; a non-empty `standin` -> approx (joist_openweb_standin -> joist_envelope, member_envelope -> envelope).
  3. Caches. The table cache key is bumped (reader '3+v55') so tables parsed without the adapter are not reused.
Decoder fix (on by default; --no-decoder-fix reproduces the raw verifier):
  4. The verifier's decode/instances.py is an older copy of the converter's and accepts placement blocks whose matrix
     is not a rotation (NaN / 1e248 entries; `NaN > tol` is False). Those phantom placements become "missing" pieces
     in C1 and garbage extents in S4 (e.g. CMC_Greenville 84ed6ebb: 2 phantom L4x3 1/2 placements, S4 span 3e286 in).
     The fix drops placements whose matrix is not orthonormal (the converter's _is_frame since v5.x); the count
     dropped is reported.
  5. S4 on stage 2 falls back to a dummy 1-in reference box when it can rebuild no piece box and decodes no member
     (stub-member jobs): reported NA ("no reference extent") instead of FAIL.
Grading policy (on by default; --no-policy keeps the verifier's own statuses). Decided 2026-10-02 for the class-1 gate;
every changed result keeps the verifier's status in metrics.policy.verifier_status. NOTE = recorded for audit, status
NA, so it does not enter the verdict or the tier:
  6. stage-2 member-decoder checks D1-D6 -> NOTE (cause verifier) once pieces were decoded (the verifier already ignores
     their FAIL for stage 2; their WARN no longer makes "with warnings").
     C1 -> FAIL (cause pipeline) only for missing pieces the converter's own manifest does not list; otherwise NOTE
     (its piece decoder is an older copy of ours).
     G2 / G3 -> NOTE (false positives on steel-in-concrete models: 6eeedc27 column segments between slabs).
     G4 -> each identical-solid group split: one SDS2 piece id under two non-twin members, or a member's main material
     twice in one member (EC-27) = converter-made -> FAIL (cause pipeline); twin members, the same piece twice in one
     member, or two piece records = source -> WARN (cause source).
     M1 -> judged on the parts the converter claims exact (approx-tagged / envelope / joist parts left out; they are
     class 2 already); the all-parts result is kept in metrics.all_parts.
     M2 -> NOTE (cause source) when SDS2's recorded joist weights are series placeholders (2.5 / 5.0 lb/ft, or under half
     the SJI catalogue weight): the joist stand-ins are sized to the catalogue.
     E2 / E3 -> NOTE (cause ground_truth_other_revision) when section recall < 60 % and >= 25 % of the truth quantity has
     a section absent from the SDS2 job (Greenwood: ~950 studs); otherwise the verifier's status (cause pipeline).
  v3 (2026-10-02, after the first fleet run): only real converter defects decide.
     D1-D6 -> NOTE on both stages (verifier's member decoder), unless nothing at all was decoded (CANNOT VERIFY).
     Stage 1: when that decoder fails (D3 / D4 / D6 FAIL) the member-based checks C1 / S4 / M1 / G1 -> NOTE.
     G1 on stage 2 -> NOTE.
     S4 -> FAIL only for a units / scale error (every non-degenerate axis off > 5x the same way); other extent
     differences -> NOTE (planar frames give a 1-in reference axis; few rebuildable pieces give a partial reference).
     G5 -> rebuilt again from each piece's own topology vertices (brep_v55.parse) under the same decoded transform; the
     verifier's raw vertex records include non-geometry points (EC-45). FAIL / WARN only if that rebuild fails too.
     G4 -> twin members are SDS2's own duplicate members (source): same solids, or same type / section / work line by
     the verifier's member decoder or, where that cannot read the job, by the converter's (bundled sds2job_v55).
     S2 -> open surfaces as stored (reference models, tagged open surfaces) are left out of the shares.
     M2 -> NOTE when every joist solid is a tagged stand-in (class 2 already).
The report JSON gains an `adapter` block saying what was applied.
"""
import os, re, sys, json, argparse


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--verifier", required=True)
    ap.add_argument("--no-decoder-fix", action="store_true")
    ap.add_argument("--no-policy", action="store_true")
    a, rest = ap.parse_known_args()
    root = os.path.abspath(a.verifier)
    sys.path.insert(0, os.path.join(root, "verify")); sys.path.insert(0, os.path.join(root, "decode"))
    import numpy as np
    import steptable, tiers, verify as V
    stats = dict(names_reparsed=0, joist_standins=0, reference_parts=0, phantom_placements_dropped=0)

    # 1. names
    TAG = re.compile(r"\s\[(approx|reference|derived): .*\]\s*$", re.S)
    JOIST = re.compile(r"^\s*(?:(?P<type>.+?) )?#(?P<mid>\d+) / (?P<pname>.+) \(joist stand-in\)$")
    orig_parse = steptable.parse_name

    def parse_name(name):
        m = TAG.search(name or "")
        if not m:
            return orig_parse(name)
        base, kind = name[:m.start()], m.group(1)
        j = JOIST.match(base)
        if j:
            r = dict(stage="piece", member_type=j["type"] or "", member_id=int(j["mid"]), piece_id=0, section=j["pname"],
                     inst=None, approx=False, tags=["member_envelope"])
        else:
            r = orig_parse(base)
        if r["stage"] in ("piece", "member"):
            if kind == "approx" and "approx" not in r["tags"] and "member_envelope" not in r["tags"]:
                r["tags"] = list(r["tags"]) + ["approx"]; r["approx"] = True
            elif kind == "reference":
                r["tags"] = list(r["tags"]) + ["reference"]
        return r

    steptable.parse_name = parse_name; tiers.parse_name = parse_name
    steptable.READER = "3+v55"

    # 2. manifest
    tiers.BUILDER_TAGS.update({"joist_openweb_standin": "joist_envelope", "member_envelope": "member_envelope",
                               "piece_table_standin": "approx", "plate_hull_fallback": "approx", "vertex_box_fallback": "approx",
                               "bent_plate_fallback": "approx", "exact_brep_unvalidated": "approx"})
    orig_mt = tiers._manifest_tags

    def manifest_tags(row):
        t = orig_mt(row)
        if (row.get("standin") or "").strip() and not t & {"joist_envelope", "member_envelope"}:
            t.add("approx")
        return t
    tiers._manifest_tags = manifest_tags

    # 4. decoder fix
    if not a.no_decoder_fix:
        import instances

        def is_frame(M):
            M = np.asarray(M, float)
            with np.errstate(all="ignore"):
                if not np.isfinite(M).all() or np.abs(M).max() > 1.0 + 1e-6:
                    return False
                return bool(np.abs(M @ M.T - np.eye(3)).max() <= 1e-3 and abs(abs(np.linalg.det(M)) - 1) <= 1e-3)
        orig_mi = instances.material_instances

        def material_instances(job, n, pieces):
            main, out = orig_mi(job, n, pieces)
            keep = [x for x in out if is_frame(x[1])]
            stats["phantom_placements_dropped"] += len(out) - len(keep)
            return main, keep
        instances.material_instances = material_instances

    # 5. S4 with no reference extent (decoder fix): stage-2 S4 compares with decoded piece boxes, else with member work
    # points. When the verifier can rebuild < 10 piece boxes and decodes no structural member (stub-member jobs, e.g.
    # 6eeedc27: D1 FAIL, 0 boxes) the reference is a dummy 1-in box and S4 FAILs on any real model: report NA instead.
    if not a.no_decoder_fix:
        import checks as C
        orig_s4 = C.s4_units_extent

        def s4_units_extent(ctx):
            r = orig_s4(ctx)
            ref = r.metrics.get("decoded_span_in") or []
            if r.status in ("FAIL", "WARN") and ref and max(ref) <= 1.0 and ctx.step_unit == "MM":
                stats["s4_no_reference_extent"] = True
                r.status, r.reason = "NA", "no reference extent: no decoded piece boxes and no decoded members (adapter)"
            return r
        s4_units_extent.__name__ = "s4_units_extent"
        for L in (C.ALL, C.TABLE_CHECKS):
            for i, f in enumerate(L):
                if f is orig_s4:
                    L[i] = s4_units_extent

    # 6. grading policy, applied to the full check list before the verifier computes its verdict and tier
    if not a.no_policy:
        import checks as C
        install_policy(C, V, stats)

    # caches the raw verifier wrote next to the STEP depend on the decoder: recompute
    sys.argv = [os.path.join(root, "verify", "verify.py")] + rest
    args = V.argparse.ArgumentParser(add_help=False); args.add_argument("--step"); args.add_argument("--out")
    k, _ = args.parse_known_args(rest)
    if k.step:
        for suf in (".expected_all.json", ".expected.json"):
            if os.path.exists(k.step + suf):
                os.remove(k.step + suf)
    V.main()
    if k.step:
        prefix = k.out or os.path.splitext(k.step)[0] + "_verify"
        rep = json.load(open(prefix + ".json"))
        tab = json.load(open(k.step + ".table.json"))["solids"]
        stats["names_reparsed"] = sum(1 for t in tab if TAG.search(t["name"] or ""))
        stats["joist_standins"] = sum(1 for t in tab if "(joist stand-in)" in (t["name"] or ""))
        stats["reference_parts"] = sum(1 for t in tab if "reference" in (t.get("tags") or []))
        stats["unparsed_after_adapter"] = sum(1 for t in tab if t["stage"] == "unknown")
        rep["adapter"] = dict(name="verify_v55_v3", for_converter="sds2-step-pipeline v5.5.x", verifier="sds2_step_verifier v1.3.3",
                              decoder_fix=not a.no_decoder_fix, policy=not a.no_policy, **stats)
        json.dump(rep, open(prefix + ".json", "w"), indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
        print("ADAPTER", json.dumps(rep["adapter"]))


# SJI K-series typical weight (lb/ft), standard load tables (same table as the converter's joist.py)
SJI_K = {
    "8K1": 5.1, "10K1": 5.0, "12K1": 5.0, "12K3": 5.7, "12K5": 7.1, "14K1": 5.2, "14K3": 6.0, "14K4": 6.7,
    "14K6": 7.7, "16K2": 5.5, "16K3": 6.3, "16K4": 7.0, "16K5": 7.5, "16K6": 8.1, "16K7": 8.6, "16K9": 10.0,
    "18K3": 6.6, "18K4": 7.2, "18K5": 7.7, "18K6": 8.5, "18K7": 9.0, "18K9": 10.2, "18K10": 11.7, "20K3": 6.7,
    "20K4": 7.6, "20K5": 8.2, "20K6": 8.9, "20K7": 9.3, "20K9": 10.8, "20K10": 12.2, "22K4": 8.0, "22K5": 8.8,
    "22K6": 9.2, "22K7": 9.7, "22K9": 11.3, "22K10": 12.6, "22K11": 13.8, "24K4": 8.4, "24K5": 9.3, "24K6": 9.7,
    "24K7": 10.1, "24K8": 11.5, "24K9": 12.0, "24K10": 13.1, "24K12": 16.0, "26K5": 9.8, "26K6": 10.6,
    "26K7": 10.9, "26K8": 12.1, "26K9": 12.2, "26K10": 13.8, "26K12": 16.6, "28K6": 11.4, "28K7": 11.8,
    "28K8": 12.7, "28K9": 13.0, "28K10": 14.3, "28K12": 17.1, "30K7": 12.3, "30K8": 13.2, "30K9": 13.4,
    "30K10": 15.0, "30K11": 16.4, "30K12": 17.6,
}
DESIG = re.compile(r"^(\d+(?:\.\d+)?)\s*(KCS|DSLH|SLH|DLH|LH|CJ|K|BG|VG|JG|G)(\d+)?", re.I)


def sji_typical(name):
    key = (name or "").upper().split("/")[0].strip()
    if key in SJI_K:
        return SJI_K[key]
    m = DESIG.match(key)
    if not m:
        return None
    d, size, series = float(m.group(1)), int(m.group(3)) if m.group(3) else 6, m.group(2).upper()
    if series in ("K", "KCS"):
        return round(3.0 + 0.16 * d + 0.55 * size, 1)
    if series in ("LH", "SLH"):
        return round(4.0 + 0.25 * d + 1.1 * size, 1)
    if series in ("DLH", "DSLH"):
        return round(6.0 + 0.30 * d + 1.4 * size, 1)
    return round(max(5.0, 0.4 * d), 1)


def install_policy(C, V, stats):
    import collections
    import numpy as np
    orig_bc, orig_rc = C._bom_compare, V.run_checks
    SOFT_TAGS = {"approx", "joist_envelope", "member_envelope", "grating_envelope"}

    def bom_compare(ctx, truth):
        met, status = orig_bc(ctx, truth)
        try:
            from groundtruth import canon
            from piece_table import read_pieces
            names = {canon(p.get("name") or "") for p in read_pieces(ctx.job).values()}
            names |= {canon(m.section.name) for m in ctx.members if m.section is not None and m.section.name}
            tot = sum(q for s_, L, q in truth)
            absent = sum(q for s_, L, q in truth if canon(s_) not in names)
            met["absent_from_job_share"] = round(absent / tot, 4) if tot else None
        except Exception as ex:                                          # never change the check because of this
            met["absent_from_job_share"] = None; met["absent_error"] = f"{type(ex).__name__}: {ex}"[:120]
        return met, status
    C._bom_compare = bom_compare

    def note(r, cause, why):
        r.metrics = dict(r.metrics, policy=dict(level="NOTE", cause=cause, verifier_status=r.status, why=why))
        r.reason = f"NOTE ({why}); verifier: {r.status}" + (f" - {r.reason}" if r.reason else "")
        r.status = "NA"
        stats.setdefault("policy_notes", []).append(r.id)

    def tag(r, cause, why="", status=None):
        r.metrics = dict(r.metrics, policy=dict(level=status or r.status, cause=cause, verifier_status=r.status, why=why))
        if why:
            r.reason = f"{why}; verifier: {r.status}" + (f" - {r.reason}" if r.reason else "")
        if status:
            r.status = status

    def g4_split(ctx):
        groups = collections.defaultdict(list)
        for t in ctx.table:
            groups[(round(t["volume"], 2), *[round(v, 2) for v in t["lo"] + t["hi"]])].append(t)
        twin = {m.id: (m.type, m.section.name if m.section else "",
                       tuple(sorted([tuple(np.round(m.p1, 2).tolist()), tuple(np.round(m.p2, 2).tolist())]))) for m in ctx.members}
        mains = {}

        def main_of(mid):
            if mid not in mains:
                try:
                    from instances import material_instances
                    from piece_table import read_pieces
                    mains[mid] = material_instances(ctx.job, mid, read_pieces(ctx.job))[0]
                except Exception:
                    mains[mid] = None
            return mains[mid]
        # v5.5.11+ manifests list the duplicates the converter kept as SDS2's own (twin members by the converter's
        # member decoder, same member, two piece records): those are source whatever the verifier's member decoder says
        kept_src = set()
        try:
            man = json.load(open(os.path.splitext(ctx.step_path)[0] + "_manifest.json"))
            for q in (man.get("source_duplicate_placements") or {}).get("parts") or []:
                kept_src.add((int(q["member"]), int(q["piece"]), int(q["inst"])))
        except Exception:
            pass
        # members whose solids are all identical to another member's: SDS2 duplicated the member itself (twin by content;
        # the verifier's member decoder misses untyped members, e.g. data-3 1f9bb631 railings #7 / #9)
        gid = {}
        for k_, g in enumerate(groups.values()):
            for t in g:
                gid[id(t)] = k_
        content = collections.defaultdict(collections.Counter)
        for t in ctx.table:
            if t.get("member_id") is not None:
                content[t["member_id"]][gid[id(t)]] += 1
        ours = {}

        def our_twin(a, b):
            """twin members by the converter's member decoder (bundled sds2job_v55), for jobs the verifier's own member
            decoder cannot read (stub-member jobs: '2 members in mem_idx')"""
            if not ours:
                try:
                    import sds2job_v55
                    ms, _ = sds2job_v55.read_members(ctx.job)
                    ours.update({m.id: (m.type, m.section.name if m.section else None,
                                        tuple(sorted([tuple(np.round(m.p1, 2).tolist()), tuple(np.round(m.p2, 2).tolist())])))
                                 for m in ms})
                except Exception:
                    ours[None] = None
            return ours.get(a) is not None and ours.get(a) == ours.get(b)
        conv, src, ex_c, ex_s = 0, 0, [], []
        false_dup = []
        for g in groups.values():
            if len(g) < 2:
                continue
            for k_, t in enumerate(g[1:], 1):
                # each extra copy against every earlier copy of the group; converter-made if any relation says so
                verdict_, why_ = None, ""
                for first in g[:k_]:
                    if t.get("piece_id") and first.get("piece_id"):
                        same = same_solid(placed_topology(ctx, first), placed_topology(ctx, t))
                        if same is False:          # same box and volume, different solid (crossing X-brace rods)
                            continue
                    if (t["member_id"], t.get("piece_id"), t.get("inst")) in kept_src or \
                            (first["member_id"], first.get("piece_id"), first.get("inst")) in kept_src:
                        verdict_ = verdict_ or ("src", f"{first['name']} = {t['name']} (listed by the converter as SDS2's own)"); continue
                    same_piece = t.get("piece_id") and t.get("piece_id") == first.get("piece_id")
                    diff_member = t["member_id"] != first["member_id"]
                    is_twin = diff_member and ((twin.get(t["member_id"]) is not None and twin.get(t["member_id"]) == twin.get(first["member_id"]))
                                               or content.get(t["member_id"]) == content.get(first["member_id"])
                                               or our_twin(t["member_id"], first["member_id"]))
                    if same_piece and diff_member and not is_twin:
                        verdict_ = ("conv", f"{first['name']} = {t['name']}"); break
                    if same_piece and not diff_member and t["piece_id"] == main_of(t["member_id"]):
                        verdict_ = ("conv", f"{first['name']} = {t['name']} (main material twice, EC-27)"); break
                    verdict_ = verdict_ or ("src", f"{first['name']} = {t['name']}")
                if verdict_ is None:
                    false_dup.append(t["name"])
                elif verdict_[0] == "conv":
                    conv += 1; ex_c.append(verdict_[1])
                else:
                    src += 1; ex_s.append(verdict_[1])
        stats["g4_false_duplicates"] = len(false_dup)
        return conv, src, ex_c[:8], ex_s[:8] + [f"not identical (same box, different solid): {x}" for x in false_dup[:4]]

    topo = {}

    def placed_topology(ctx, t):
        """The row's solid as its piece's topology vertices under the decoded placement that best fits the row's box
        (None when the piece has no readable topology or no decoded placement)."""
        try:
            import brep_v55
            from instances import material_instances
            from piece_table import read_pieces
        except Exception:
            return None
        if "P" not in topo:
            topo["P"] = read_pieces(ctx.job); topo["V"] = {}; topo["I"] = {}
        mid, sid = t.get("member_id"), t.get("piece_id")
        if not sid:
            return None
        if sid not in topo["V"]:
            V = None; pth = os.path.join(ctx.job, "subm", str(sid))
            if os.path.exists(pth):
                try:
                    r = brep_v55.parse(open(pth, "rb").read())
                    if r is not None:
                        used = sorted({i for f in r[1] for i in f})
                        if len(used) >= 4:
                            V = np.asarray(r[0], float)[used]
                except Exception:
                    V = None
            topo["V"][sid] = V
        if mid not in topo["I"]:
            try:
                topo["I"][mid] = material_instances(ctx.job, mid, topo["P"])[1]
            except Exception:
                topo["I"][mid] = []
        V = topo["V"][sid]
        cands = [o + V @ M for s_, M, o in topo["I"][mid] if s_ == sid] if V is not None else []
        if not cands:
            return None
        lo, hi = np.array(t["lo"]), np.array(t["hi"])
        return min(cands, key=lambda W: max(np.abs(lo - W.min(0)).max(), np.abs(hi - W.max(0)).max()))

    def same_solid(A, B, tol=0.05):
        if A is None or B is None:
            return None
        if A.shape != B.shape:
            return False
        from scipy.spatial import cKDTree
        return bool(cKDTree(B).query(A)[0].max() <= tol and cKDTree(A).query(B)[0].max() <= tol)

    def g5_topology(ctx):
        """Each exact piece solid's box vs its piece's topology vertices (the faces' vertices, as the converter builds
        the B-rep) under the decoded placement; approximate / envelope solids are left out (class 2 already)."""
        try:
            import brep_v55
            from instances import material_instances
            from piece_table import read_pieces
        except Exception as ex:
            return dict(status="NA", error=f"{type(ex).__name__}: {ex}"[:120])
        P = read_pieces(ctx.job); vcache, icache, errs, n, nomatch = {}, {}, [], 0, 0

        def vused(sid):
            if sid not in vcache:
                V = None; pth = os.path.join(ctx.job, "subm", str(sid))
                if os.path.exists(pth):
                    try:
                        r = brep_v55.parse(open(pth, "rb").read())
                        if r is not None:
                            used = sorted({i for f in r[1] for i in f})
                            if len(used) >= 4:
                                V = np.asarray(r[0], float)[used]
                    except Exception:
                        V = None
                vcache[sid] = V
            return vcache[sid]
        for t in ctx.table:
            if not t.get("piece_id") or set(t.get("tags") or []) & SOFT_TAGS:
                continue
            mid, sid = t["member_id"], t["piece_id"]
            if mid not in icache:
                try:
                    icache[mid] = material_instances(ctx.job, mid, P)[1]
                except Exception:
                    icache[mid] = []
            V = vused(sid); cands = [(o, M) for s_, M, o in icache[mid] if s_ == sid]
            n += 1
            if V is None or not cands:
                nomatch += 1; continue
            lo, hi = np.array(t["lo"]), np.array(t["hi"])
            errs.append(min(max(np.abs(lo - W.min(0)).max(), np.abs(hi - W.max(0)).max()) for W in (o + V @ M for o, M in cands)))
        if not errs:
            return dict(status="NA", solids=n, rebuilt=0, no_topology=nomatch)
        a = np.array(errs); share = float(np.mean(a <= 3.0))
        return dict(status="PASS" if share >= 0.95 else ("WARN" if share >= 0.85 else "FAIL"), solids=n, rebuilt=len(a),
                    no_topology=nomatch, within_3in=round(share, 4), within_0_1in=round(float(np.mean(a <= 0.1)), 4),
                    p99_err_in=round(float(np.percentile(a, 99)), 3))

    def apply(ctx, results):
        st = {r.id: r for r in results}
        stage2 = ctx.stage == "piece"
        c1 = st.get("C1")
        decoded = stage2 and c1 is not None and (c1.metrics.get("expected_pieces") or 0) > 0
        decoded1 = (not stage2) and bool(getattr(ctx, "members", None))
        member_decoder_bad = any(st.get(d) is not None and st[d].status == "FAIL" for d in ("D3", "D4", "D6"))
        for d in ("D1", "D2", "D3", "D4", "D5", "D6"):
            r = st.get(d)
            if r is not None and r.status in ("WARN", "FAIL") and ((decoded or decoded1) or d not in ("D1", "D2")):
                note(r, "source" if d == "D5" else "verifier", "the verifier's own member-decoder check" +
                     ("; stage-2 geometry comes from piece placements" if stage2 else ""))
        if not stage2 and member_decoder_bad:
            for k_ in ("C1", "S4", "M1", "G1"):
                r = st.get(k_)
                if r is not None and r.status in ("WARN", "FAIL"):
                    note(r, "verifier", "judged against the verifier's member decode, which failed its own checks on this job")
        g1 = st.get("G1")
        if g1 is not None and stage2 and g1.status in ("WARN", "FAIL"):
            note(g1, "verifier", "work-line check does not apply to stage-2 pieces")
        s4 = st.get("S4")
        if s4 is not None and s4.status in ("WARN", "FAIL"):
            ratio, ref = s4.metrics.get("span_ratio") or [], s4.metrics.get("decoded_span_in") or []
            axes = [r_ for r_, d_ in zip(ratio, ref) if d_ > 1.5]
            if s4.metrics.get("file_unit") not in (None, "MM"):
                tag(s4, "pipeline")
            elif axes and (all(r_ > 5 for r_ in axes) or all(r_ < 0.2 for r_ in axes)):
                tag(s4, "pipeline", "every non-degenerate axis off the same way: units / scale")
            else:
                note(s4, "verifier", "extent differs from a degenerate or partial reference (planar frame / few rebuildable "
                                     "pieces), not a units error")
        g5 = st.get("G5")
        if g5 is not None and stage2 and g5.status in ("WARN", "FAIL"):
            res5 = g5_topology(ctx)
            g5.metrics = dict(g5.metrics, topology_rebuild=res5)
            if res5.get("status") in ("PASS", "NA"):
                note(g5, "verifier", f"rebuilt from each piece's topology vertices: {res5.get('within_3in')} within 3 in "
                                     "(the verifier's raw vertex records include non-geometry points, EC-45)")
            else:
                tag(g5, "pipeline", f"also off when rebuilt from the pieces' topology vertices ({res5.get('within_3in')} within 3 in)",
                    res5["status"])
        s2 = st.get("S2")
        if s2 is not None and s2.status in ("WARN", "FAIL") and "multi-body" not in (s2.reason or ""):
            T2 = [t for t in ctx.table if not ("reference" in (t.get("tags") or []) or "open surface" in (t.get("name") or ""))]
            if T2 and len(T2) < len(ctx.table):
                ok = min(np.mean([t["valid"] for t in T2]), np.mean([t["closed"] for t in T2]), np.mean([t["volume"] > 1e-6 for t in T2]))
                s2.metrics = dict(s2.metrics, without_open_surfaces=round(float(ok), 5), open_surfaces=len(ctx.table) - len(T2))
                if ok >= 0.995:
                    note(s2, "by_design", f"{len(ctx.table) - len(T2)} open surfaces as stored (reference / tagged); the rest pass")
        if c1 is not None and stage2 and c1.status in ("WARN", "FAIL"):
            items = getattr(ctx, "missing_items", None) or []
            unlisted = sum(int(m.get("count") or 1) for m in items if not (m.get("converter_reason") or "").strip())
            c1.metrics = dict(c1.metrics, unlisted_missing=unlisted)
            if unlisted:
                tag(c1, "pipeline", f"{unlisted} expected piece(s) missing that the converter's manifest does not list", "FAIL")
            else:
                note(c1, "pipeline", "every missing piece is listed by the converter's own manifest, or only approximate "
                                     "solids / unexpected items (its piece decoder is an older copy of the converter's)")
        for g in ("G2", "G3"):
            r = st.get(g)
            if r is not None and r.status in ("WARN", "FAIL"):
                note(r, "pipeline", "audit only: connectivity false positives on steel-in-concrete models")
        g4 = st.get("G4")
        if g4 is not None and g4.status != "NA":
            conv, src, ex_c, ex_s = g4_split(ctx)
            g4.metrics = dict(g4.metrics, introduced_by_converter=conv, already_in_sds2_job=src, duplicates=conv + src,
                              converter_examples=ex_c, source_examples=ex_s)
            if conv:
                tag(g4, "pipeline", f"{conv} repeat solid(s) made by the converter (one SDS2 piece written twice)", "FAIL")
            elif src:
                tag(g4, "source", f"{src} identical solid(s) placed twice by SDS2's own data (kept as stored)", "WARN")
            else:
                tag(g4, "pipeline", "", "PASS")
        m1 = st.get("M1")
        if m1 is not None:
            keep = ctx.table
            try:
                ctx.table = [t for t in keep if not (set(t.get("tags") or []) & SOFT_TAGS)]
                r_ex = C.m1_mass(ctx)
            finally:
                ctx.table = keep
            allp = dict(status=m1.status, reason=m1.reason, families_off=m1.metrics.get("families_off"),
                        within_tol_share=m1.metrics.get("within_tol_share"), compared=m1.metrics.get("compared"))
            m1.metrics = dict(r_ex.metrics, all_parts=allp)
            why = "judged on the parts claimed exact"
            if allp["status"] in ("WARN", "FAIL") and r_ex.status in ("PASS", "NA"):
                why += f"; all parts {allp['status']} only because of approximate parts (already class 2)"
            m1.metrics["policy"] = dict(level=r_ex.status, cause="pipeline", verifier_status=allp["status"], why=why)
            m1.status, m1.reason = r_ex.status, (r_ex.reason or "") + (f" ({why})" if allp["status"] != r_ex.status else "")
        m2 = st.get("M2")
        J = [t for t in ctx.table if C.is_joist(t)]
        if m2 is not None and m2.status in ("WARN", "FAIL") and J and all(set(t.get("tags") or []) & SOFT_TAGS for t in J):
            note(m2, "pipeline", "every joist solid is a tagged stand-in (class 2 already)")
        elif m2 is not None and m2.status in ("WARN", "FAIL"):
            if m2.status == "WARN" and "no recorded weight" in (m2.reason or ""):
                note(m2, "source", "SDS2 records no joist weight")
            else:
                n = ph = 0; ex = []
                for t in ctx.table:
                    if not C.is_joist(t):
                        continue
                    m = ctx.member_by_id.get(t["member_id"])
                    if not m or not m.section or not (m.section.weight or 0) > 0:
                        continue
                    n += 1; rec, typ = float(m.section.weight), sji_typical(m.section.name)
                    if rec in (2.5, 5.0) or (typ and rec < 0.5 * typ):
                        ph += 1
                        if len(ex) < 4: ex.append(f"{m.section.name}: SDS2 {rec:g} lb/ft, SJI ~{typ} lb/ft")
                m2.metrics = dict(m2.metrics, placeholder_weight_joists=ph, weighed_joists=n, placeholder_examples=ex)
                if n and ph >= 0.9 * n:
                    note(m2, "source", f"SDS2's recorded joist weights are placeholders ({ph} of {n}); stand-ins use the SJI catalogue")
                else:
                    tag(m2, "pipeline")
        for e in ("E2", "E3"):
            r = st.get(e)
            if r is not None and r.status in ("WARN", "FAIL"):
                rec_, ab = r.metrics.get("section_recall"), r.metrics.get("absent_from_job_share")
                if rec_ is not None and rec_ < 0.6 and ab is not None and ab >= 0.25:
                    note(r, "ground_truth_other_revision", f"section recall {rec_:.0%}, {ab:.0%} of the truth quantity has a "
                                                           "section absent from the SDS2 job: truth is another revision")
                else:
                    tag(r, "pipeline")
        s2 = st.get("S2")
        if s2 is not None and s2.status == "WARN" and "multi-body" in (s2.reason or ""):
            tag(s2, "by_design")
        return results

    def run_checks(ctx, fns):
        res = orig_rc(ctx, fns)
        return apply(ctx, res) if fns is C.ALL else res
    V.run_checks = run_checks


if __name__ == "__main__":
    main()
