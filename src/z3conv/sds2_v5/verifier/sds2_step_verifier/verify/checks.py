"""Verification checks for SDS2 -> STEP conversions.

Every check returns Result(id, title, status, metrics, reason). status is PASS / WARN / FAIL / NA.
NA means "no evidence either way" (e.g. no IFC for this job) and never counts as a pass.

Check families
  D  decode sanity on the raw job (before STEP): version gate, shape table, section field, geometry fields, outliers
  S  STEP integrity: parse, solid count vs manifest, B-rep validity, names, units/extent
  M  mass: STEP volume x steel density vs SDS2's own recorded weights (independent of our geometry code)
  G  internal geometry: solid vs work line, top-of-steel, connectivity, piece-to-parent, duplicates
  E  external ground truth: SDS2 IFC export (auto-aligned), KISS bill of materials, DSTV NC1 parts
Edge cases each check guards against are listed in EDGE_CASES.md (ids EC-xx).
"""
import os, re, math, struct, random, collections
from dataclasses import dataclass, field
import numpy as np

STEEL_LB_PER_IN3 = 0.2836          # 490 lb/ft^3
STRUCTURAL = {"BEAM", "COLUMN", "VERTICAL BRACE", "HORIZONTAL BRACE", "PL GIRDER", "JOIST", "KICKER"}
SLOT_FAMILY = {2494: "7.2xx", 2944: "7.3xx", 2976: "7.4xx"}
SUPPORTED = {"7.2xx": "full", "7.3xx": "members"}   # pieces decoder validated on 7.2xx only
AISC = {  # d, bf, tf, tw  (AISC Shapes Database v15)
    "W18x35": (17.7, 6.0, 0.425, 0.3), "W12x19": (12.2, 4.01, 0.35, 0.235), "W14x22": (13.7, 5.0, 0.335, 0.23),
    "W8x31": (8.0, 8.0, 0.435, 0.285), "W10x12": (9.87, 3.96, 0.21, 0.19), "W24x55": (23.6, 7.01, 0.505, 0.395),
    "W14x455": (19.0, 16.8, 3.21, 2.02), "W21x44": (20.7, 6.5, 0.45, 0.35), "W16x26": (15.7, 5.5, 0.345, 0.25),
    "W27x84": (26.7, 10.0, 0.64, 0.46), "C8x11.5": (8.0, 2.26, 0.39, 0.22), "W30x99": (29.7, 10.5, 0.67, 0.52),
}


@dataclass
class Result:
    id: str
    title: str
    status: str = "NA"
    metrics: dict = field(default_factory=dict)
    reason: str = ""


def grade(value, pass_if, warn_if):
    """pass_if / warn_if are predicates on value."""
    return "PASS" if pass_if(value) else ("WARN" if warn_if(value) else "FAIL")


def worst(statuses):
    order = {"FAIL": 3, "WARN": 2, "PASS": 1, "NA": 0}
    return max(statuses, key=lambda s: order[s]) if statuses else "NA"


# ======================================================================= D: decode sanity
def d1_version_gate(ctx):
    r = Result("D1", "Version / layout gate")
    job = ctx.job
    ver = ctx.version or ""
    p = os.path.join(job, "mem", "mem_idx")
    if not os.path.exists(p):
        r.status, r.reason = "FAIL", "no mem/mem_idx: not an SDS2 7.x job layout (EC-46)"; return r
    idx_size = os.path.getsize(p)
    slot = ctx.layout.get("slot") if ctx.layout else None
    fam = SLOT_FAMILY.get(slot) if slot else None
    ver_fam = (ver[:3] + "xx") if re.match(r"7\.\d", ver) else None
    r.metrics = dict(jsetup_version=ver, mem_idx_size=idx_size, calibrated_slot=slot, slot_family=fam or (f"slot {slot}" if slot else None),
                     layout={k: (hex(v) if isinstance(v, int) else v) for k, v in (ctx.layout or {}).items()},
                     decode_error=getattr(ctx, "member_error", None) or getattr(ctx, "shape_error", None))
    if not ctx.layout:
        r.status, r.reason = "FAIL", "layout auto-calibration failed (EC-01/EC-06): cannot decode this job"
    elif (idx_size - 256) % slot:
        r.status, r.reason = "FAIL", f"mem_idx size is not 256 + n x calibrated slot {slot} (EC-03)"
    elif fam and ver_fam and ver_fam != fam:
        r.status, r.reason = "FAIL", f"jsetup says {ver} but slot size {slot} belongs to {fam} (EC-02)"
    elif fam in SUPPORTED and not (ctx.stage == "piece" and SUPPORTED[fam] != "full"):
        r.status = "PASS"
    elif fam in SUPPORTED:
        r.status, r.reason = "WARN", f"piece decoding is only validated on 7.2xx; {fam} pieces are judged by G5/E1/M1 (EC-05)"
    else:
        # calibrated but never validated on this version: not rejected, but trust comes only from the
        # independent checks (M1 SDS2 weights, E1 IFC, E2 KISS, E3 NC1) - EC-04
        r.status, r.reason = "WARN", f"version {ver or '?'} (slot {slot}) not validated before; trust rests on M/E checks (EC-04)"
    return r


def d2_shape_table(ctx):
    r = Result("D2", "Shape table (job_mtrl) sanity")
    try:
        from sds2job import mtrl_layout
        L, _ = mtrl_layout(ctx.job)
    except Exception as ex:
        r.status, r.reason = "FAIL", f"job_mtrl layout could not be calibrated (EC-06): {ex}"; return r
    r.metrics["layout"] = dict(record=L["rec"], base=hex(L["base"]), byte_order="big" if L["endian"] == ">" else "little",
                               dims_at=hex(L["d_off"]), weight_at=hex(L["weight_off"]), votes=L["votes"])
    shapes = ctx.shapes
    mism, checked = [], 0
    for nm, (d, bf, tf, tw) in AISC.items():
        s = next((x for x in shapes.values() if x.name == nm), None)
        if s is None: continue
        checked += 1
        if max(abs(s.d - d) / d, abs(s.bf - bf) / bf, abs(s.tf - tf) / tf, abs(s.tw - tw) / tw) > 0.03:
            mism.append((nm, (round(s.d, 3), round(s.bf, 3), round(s.tf, 3), round(s.tw, 3))))
    W = [s for s in shapes.values() if s.family == "W"]
    plaus = np.mean([3 < s.d < 45 and 0 < s.tf < s.d / 2 and 0 < s.tw < s.bf and 0 < s.bf < 20 for s in W]) if W else 0
    r.metrics.update(records=len(shapes), aisc_checked=checked, aisc_mismatch=mism, w_plausible_share=round(float(plaus), 4))
    if mism: r.status, r.reason = "FAIL", "shape dimensions disagree with AISC (EC-07: dims offset shifted)"
    elif checked == 0 or plaus < 0.99: r.status, r.reason = "WARN", "could not confirm shape dims against AISC"
    else: r.status = "PASS"
    return r


def d3_section_field(ctx):
    r = Result("D3", "Section field sanity")
    st = [m for m in ctx.members if m.type in STRUCTURAL]
    if not st:
        r.status, r.reason = "FAIL", "no structural members decoded (EC-08: wrong type offset)"; return r
    with_sec = [m for m in st if m.section]
    share = len(with_sec) / len(st)
    cnt = collections.Counter(m.section.name for m in with_sec)
    top_share = cnt.most_common(1)[0][1] / len(with_sec) if with_sec else 1
    beams = [m for m in with_sec if m.type == "BEAM"]
    fam_ok = np.mean([m.section.family in {"W", "M", "S", "HP", "C", "MC", "HSS", "TS", "L", "WT", "MT", "ST", "PLG", "WBX", "WPS", "PIPE"} for m in beams]) if beams else 1
    r.metrics = dict(structural=len(st), with_section_share=round(share, 4), distinct_sections=len(cnt),
                     top_section=cnt.most_common(1)[0] if cnt else None, top_share=round(top_share, 4), beam_family_ok=round(float(fam_ok), 4))
    if len(st) >= 50 and (top_share > 0.8 or len(cnt) < 3):
        r.status, r.reason = "FAIL", "one section dominates: section offset probably wrong (EC-09)"
    elif share < 0.6 or fam_ok < 0.7:
        r.status, r.reason = "FAIL", "most members lack a plausible section (EC-10)"
    elif share < 0.9 or fam_ok < 0.9:
        r.status, r.reason = "WARN", "some members lack a plausible section"
    else:
        r.status = "PASS"
    return r


def d4_geometry_fields(ctx):
    r = Result("D4", "Work-line / roll field sanity")
    st = [m for m in ctx.members if m.type in STRUCTURAL]
    if not st:
        r.status, r.reason = "FAIL", "no structural members decoded (EC-08)"; return r
    P1 = np.array([m.p1 for m in st]); P2 = np.array([m.p2 for m in st])
    L = np.linalg.norm(P2 - P1, axis=1)
    zero = float(np.mean(L < 0.5))
    big = float(np.mean(np.abs(np.r_[P1, P2]).max(1) > 1e6))
    raw_roll_bad = ctx.raw_roll_bad_share
    cols = [m for m in st if m.type == "COLUMN"]
    vert = np.mean([abs(m.p2[2] - m.p1[2]) > 0.95 * max(np.linalg.norm(np.subtract(m.p2, m.p1)), 1e-9) for m in cols]) if cols else 1
    beams = [m for m in st if m.type == "BEAM" and np.linalg.norm(np.subtract(m.p2, m.p1)) > 0.5]
    level = np.mean([abs(m.p2[2] - m.p1[2]) < 0.2 * np.linalg.norm(np.subtract(m.p2, m.p1)) for m in beams]) if beams else 1
    r.metrics = dict(zero_length_share=round(zero, 4), huge_coord_share=round(big, 5), raw_roll_invalid_share=round(raw_roll_bad, 4),
                     columns_vertical_share=round(float(vert), 4), beams_level_share=round(float(level), 4))
    if zero > 0.2 or big > 0.001 or vert < 0.5:
        r.status, r.reason = "FAIL", "work points look mis-decoded (EC-11 zero-length / EC-12 garbage coords / EC-13 columns not vertical)"
    elif zero > 0.05 or raw_roll_bad > 0.01 or vert < 0.8 or level < 0.6:
        r.status, r.reason = "WARN", "some work points / rolls implausible (EC-11/EC-14)"
    else:
        r.status = "PASS"
    return r


def d6_section_crosscheck(ctx):
    """Section index field vs the member's main-material piece name (two independent paths through the job).
    Catches an off-by-one or shifted section index that would still look plausible (W18x35 -> W18x40) - EC-47."""
    r = Result("D6", "Section index vs main-piece name")
    L = ctx.layout or {}
    agree, src = L.get("index_vs_name_agreement"), L.get("sec_source")
    r.metrics = dict(agreement=agree, section_source=src, piece_name_path=L.get("piece_name_path"))
    if agree is None:
        r.status, r.reason = "NA", "piece-name path not available for this job"
    elif src and src.startswith("piece_name"):
        r.status, r.reason = "WARN", "section index path broken; sections taken from piece names (EC-47)"
    else:
        r.status = grade(agree, lambda v: v >= 0.9, lambda v: v >= 0.75)
        if r.status != "PASS": r.reason = "section index disagrees with the piece names (EC-47: index off by one / wrong field)"
    return r


def d5_outliers(ctx):
    r = Result("D5", "Stray members (spatial outliers)")
    st = [m for m in ctx.members if m.type in STRUCTURAL and np.linalg.norm(np.subtract(m.p2, m.p1)) > 0.5]
    if len(st) < 10:
        r.status, r.reason = "NA", "too few members"; return r
    mid = np.array([(np.array(m.p1) + np.array(m.p2)) / 2 for m in st])
    med = np.median(mid, 0)
    d = np.linalg.norm(mid - med, axis=1)
    q1, q3 = np.percentile(d, [25, 75])
    thr = q3 + 6 * max(q3 - q1, 12)
    out = d > thr
    r.metrics = dict(members=len(st), outliers=int(out.sum()), outlier_share=round(float(out.mean()), 4), threshold_in=round(float(thr), 1))
    r.status = grade(out.mean(), lambda v: v <= 0.01, lambda v: v <= 0.1)
    if r.status != "PASS": r.reason = "members far from the building (EC-15: scratch/stray members kept in the job)"
    return r


# ======================================================================= C: completeness (independent of the converter)
CONVERTIBLE = {"BEAM", "COLUMN", "VERTICAL BRACE", "HORIZONTAL BRACE", "PL GIRDER", "JOIST", "ANGLE", "KICKER", "EMBED", "MISC"}


def expected_instances(ctx):
    """Every placed material instance in the job, whether or not its geometry is parseable: (member, piece) -> count.
    Cached next to the STEP as <step>.expected_all.json."""
    import json
    cache = ctx.step_path + ".expected_all.json"
    if os.path.exists(cache) and os.path.getmtime(cache) > os.path.getmtime(ctx.step_path):
        return {tuple(map(int, k.split(":"))): v for k, v in json.load(open(cache)).items()}
    from instances import material_instances
    from piece_table import read_pieces
    pieces = read_pieces(ctx.job)
    out = collections.Counter()
    for mid in piece_member_ids(ctx):
        for sid, M, o in material_instances(ctx.job, mid, pieces)[1]:
            out[(mid, sid)] += 1
    json.dump({f"{a}:{b}": c for (a, b), c in out.items()}, open(cache, "w"))
    return out


def piece_member_ids(ctx):
    """Members whose placed pieces are expected. From the decoded member index; when the verifier's member decoder
    can't read this job (e.g. an unsupported job_mtrl layout), straight from the job's mem/<n> files - piece
    placements don't depend on the member index."""
    ids = [m.id for m in ctx.members if m.type != "Ref Point"]
    if ids:
        return ids
    md = os.path.join(ctx.job, "mem")
    return sorted(int(n) for n in os.listdir(md) if n.isdigit()) if os.path.isdir(md) else []


def c1_completeness(ctx):
    """What SHOULD be in the STEP, decoded from the SDS2 job by the verifier itself, vs what IS in it.
    Stage 1: every member of a convertible type with a section and a non-zero work line.
    Stage 2: every placed material instance (including pieces whose geometry the converter could not read).
    Lists the missing and unexpected items, so 'something is missing' names exactly what."""
    r = Result("C1", "Completeness vs the SDS2 job (independent)")
    if ctx.stage == "member":
        exp = {m.id: m for m in ctx.members if m.type in CONVERTIBLE and m.section is not None and m.section.name
               and np.linalg.norm(np.subtract(m.p2, m.p1)) >= 0.5}
        got = collections.Counter(t["member_id"] for t in ctx.table)
        missing = sorted(i for i in exp if got[i] == 0)
        extra = sorted(i for i in got if i not in exp)
        dup = sorted(i for i, c in got.items() if c > 1)
        n = len(exp)
        r.metrics = dict(expected_members=n, present=n - len(missing), missing=len(missing), unexpected=len(extra), repeated=len(dup),
                         missing_by_type=dict(collections.Counter(exp[i].type for i in missing).most_common(6)),
                         missing_examples=[f"#{i} {exp[i].type} {exp[i].section.name}" for i in missing[:12]])
        ctx.missing_items = [dict(member=i, type=exp[i].type, section=exp[i].section.name) for i in missing]
    elif ctx.stage == "piece":
        exp = expected_instances(ctx)
        got = collections.Counter((t["member_id"], t["piece_id"]) for t in ctx.table)
        # a physical piece shared by two members may be written once and recorded as `also_on_member` in the
        # manifest (fix for EC-27 cross-member duplicates): that owner's instance is present, not missing
        shared = 0
        for row in getattr(ctx, "manifest_rows", None) or []:
            for other in re.split(r"[;, ]+", (row.get("also_on_member") or "").strip()):
                if other.isdigit() and row.get("piece", "").isdigit():
                    got[(int(other), int(row["piece"]))] += 1; shared += 1
        approx = sum(1 for t in ctx.table if t.get("approx"))
        missing = {k: c - got.get(k, 0) for k, c in exp.items() if c > got.get(k, 0)}
        extra = {k: c - exp.get(k, 0) for k, c in got.items() if c > exp.get(k, 0)}
        # a member with no fabricated pieces (joists) is written whole as its envelope, piece 0: present, not extra
        with_pieces = {m for m, _ in exp}
        envelopes = sum(c for (m, p), c in got.items() if p == 0 and m not in with_pieces)
        extra = {k: c for k, c in extra.items() if not (k[1] == 0 and k[0] not in with_pieces)}
        n = sum(exp.values()); nm = sum(missing.values())
        from piece_table import read_pieces, kind
        P = read_pieces(ctx.job)
        r.metrics = dict(expected_pieces=n, present=n - nm, missing=nm, unexpected=sum(extra.values()),
                         shared_recorded_once=shared, approximate_solids=approx, member_envelopes=envelopes,
                         missing_by_kind=dict(collections.Counter(kind(P[k[1]]) if k[1] in P else "?" for k, c in missing.items() for _ in range(c))),
                         missing_examples=[f"member #{a} piece {b} {P[b]['name'] if b in P else '?'} x{c}" for (a, b), c in list(missing.items())[:12]])
        # v4 converter lists every placed piece it could not build, with the reason (<step>_skipped.csv)
        skip = collections.defaultdict(list)
        for row in getattr(ctx, "skipped_rows", None) or []:
            if (row.get("member") or "").isdigit() and (row.get("piece") or "").isdigit():
                skip[(int(row["member"]), int(row["piece"]))].append(row.get("reason") or "?")
        reasons = collections.Counter(x for k in missing for x in skip.get(k, [])[:missing[k]])
        r.metrics["missing_reported_by_converter"] = sum(reasons.values())
        r.metrics["converter_skip_reasons"] = dict(reasons.most_common(6))
        ctx.missing_items = [dict(member=a, piece=b, name=P[b]["name"] if b in P else "", count=c,
                                  converter_reason="; ".join(sorted(set(skip.get((a, b), [])))))
                             for (a, b), c in missing.items()]
        missing = list(missing)
    else:
        r.status, r.reason = "NA", "no STEP"; return r
    share = (len(missing) if ctx.stage == "member" else r.metrics["missing"]) / max(1, (n if ctx.stage == "member" else r.metrics["expected_pieces"]))
    r.metrics["missing_share"] = round(share, 5)
    r.status = grade(share, lambda v: v <= 0.001, lambda v: v <= 0.02)
    if ctx.stage == "piece" and not r.metrics["expected_pieces"]:
        # nothing decodable to compare with (SOUTH_URBAN_REVIT: 0 placed pieces): not a pass
        r.status, r.reason = "WARN", "no placed pieces could be decoded from the SDS2 job: completeness not checkable"
        return r
    if r.metrics["unexpected"] and r.status == "PASS": r.status = "WARN"
    apx = r.metrics.get("approximate_solids") or 0
    if apx and apx / max(1, len(ctx.table)) > 0.05 and r.status == "PASS":
        r.status, r.reason = "WARN", f"{apx} solids ({apx / len(ctx.table):.0%}) are approximations built from the piece table, not exact geometry"
    if r.status != "PASS":
        r.reason = f"{r.metrics['missing']} expected items are missing from the STEP" + (f", {r.metrics['unexpected']} unexpected" if r.metrics["unexpected"] else "")
    return r


# ======================================================================= S: STEP integrity
def s1_count(ctx):
    r = Result("S1", "Solid count vs manifest")
    n_step = len(ctx.table); n_man = ctx.manifest_count
    r.metrics = dict(step_solids=n_step, manifest_solids=n_man)
    if n_man is None: r.status, r.reason = "NA", "no manifest"
    elif n_step == n_man: r.status = "PASS"
    else: r.status, r.reason = "FAIL", "STEP lost or gained solids vs what the converter wrote (EC-16)"
    return r


def fastener_keys(ctx):
    """(member, piece) of fasteners per the converter manifest: SDS2 bolt / stud pieces are written as compounds
    (head, nut, washer, shank), so 'one solid per row' does not apply to them."""
    if not hasattr(ctx, "_fastener_keys"):
        ctx._fastener_keys = {(int(r["member"]), int(r["piece"])) for r in getattr(ctx, "manifest_rows", None) or []
                              if r.get("kind") == "fastener" and (r.get("member") or "").isdigit() and (r.get("piece") or "").isdigit()}
    return ctx._fastener_keys


def s2_validity(ctx):
    r = Result("S2", "B-rep validity")
    T = ctx.table
    if not T: r.status = "FAIL"; r.reason = "no solids"; return r
    valid = np.mean([t["valid"] for t in T]); closed = np.mean([t["closed"] for t in T])
    F = fastener_keys(ctx)
    single = [t["solids"] == 1 for t in T if (t["member_id"], t["piece_id"]) not in F]
    posvol = np.mean([t["volume"] > 1e-6 for t in T]); one = np.mean(single) if single else 1.0
    r.metrics = dict(valid_share=round(float(valid), 5), closed_share=round(float(closed), 5), positive_volume_share=round(float(posvol), 5), single_solid_share=round(float(one), 5))
    m = min(valid, closed, posvol)
    r.status = grade(m, lambda v: v >= 0.995, lambda v: v >= 0.98)
    if r.status != "PASS": r.reason = "invalid / open / zero-volume solids (EC-17)"
    elif one < 0.98:
        # valid, closed pieces made of several bodies are SDS2 pieces like headed anchors (HD1/2: 2 bodies, weight
        # matching SDS2's) - worth a look, not broken geometry
        r.status, r.reason = "WARN", f"{1 - one:.1%} of non-fastener pieces are multi-body solids (valid and closed)"
    return r


def s3_names(ctx):
    r = Result("S3", "Solid names parse and are unique")
    T = ctx.table
    parsed = np.mean([t["stage"] != "unknown" for t in T]) if T else 0
    # the same piece placed several times on one member carries one name (no instance number in older converters):
    # a repeated name is only a problem when the copies also sit in the same place (G4 measures true duplicates)
    by_name = collections.defaultdict(set)
    for t in T:
        by_name[t["name"]].add(tuple(np.round(t["center"], 1)))
    names = collections.Counter(t["name"] for t in T)
    dups = sum(c - len(by_name[n]) for n, c in names.items() if c > 1)
    instances = sum(len(by_name[n]) - 1 for n, c in names.items() if c > 1)
    r.metrics = dict(parsed_share=round(float(parsed), 5), duplicate_names=dups, repeated_instance_names=instances)
    r.status = "PASS" if parsed == 1 and dups == 0 else ("WARN" if parsed > 0.99 and dups <= 0.001 * len(T) else "FAIL")
    if r.status != "PASS": r.reason = "names do not trace back to SDS2 ids, or repeat (EC-18)"
    return r


def s4_units_extent(ctx):
    r = Result("S4", "Units and model extent")
    T = ctx.table
    if ctx.stage == "piece":
        # stage 2: compare with the pieces' own decoded placements (not member work points, which the verifier's
        # member decoder can get wrong on unvalidated versions while the pieces are fine); 1st-99th percentile of
        # box corners on both sides, so a few stray pieces don't decide the extent
        if not hasattr(ctx, "_exp_boxes"):
            ctx._exp_boxes = expected_piece_boxes(ctx)
        B = np.array([c for v in ctx._exp_boxes.values() for b in v for c in b])
        if len(B) >= 10:
            P = np.array([c for t in T for c in (t["lo"], t["hi"])])
            lo, hi = np.percentile(P, 1, 0), np.percentile(P, 99, 0)
            ref_lo, ref_hi = np.percentile(B, 1, 0), np.percentile(B, 99, 0)
        else:
            lo = np.min([t["lo"] for t in T], 0); hi = np.max([t["hi"] for t in T], 0)
            ref_lo, ref_hi = ctx.decoded_extent
    else:
        lo = np.min([t["lo"] for t in T], 0); hi = np.max([t["hi"] for t in T], 0)
        ref_lo, ref_hi = ctx.decoded_extent
    span, ref = hi - lo, np.maximum(ref_hi - ref_lo, 1)
    ratio = span / ref
    shift = np.abs((lo + hi) / 2 - (ref_lo + ref_hi) / 2)
    r.metrics = dict(file_unit=ctx.step_unit, span_in=np.round(span, 1).tolist(), decoded_span_in=np.round(ref, 1).tolist(),
                     span_ratio=np.round(ratio, 3).tolist(), centre_shift_in=np.round(shift, 1).tolist())
    if ctx.step_unit not in ("MM",):
        r.status, r.reason = "FAIL", f"unexpected STEP length unit {ctx.step_unit} (EC-19)"
    elif np.any(ratio > 5) or np.any(ratio < 0.2):
        r.status, r.reason = "FAIL", "model scale is off (EC-19: inches written as mm or similar)"
    elif np.any(ratio > 1.25) or np.any(ratio < 0.8) or np.any(shift > 0.1 * ref + 24):
        r.status, r.reason = "WARN", "model extent differs from the decoded work points"
    else:
        r.status = "PASS"
    return r


# ======================================================================= M: mass
JOIST_RX = re.compile(r"^\d+(K|LH|DLH|KCS|DL|G|BG|VG)\d*", re.I)   # SJI open-web joists / joist girders
# concrete pieces, and bar grating (SDS2 weighs the open mesh; the converter writes a solid panel, ~7x): no steel mass check
NOT_STEEL_RX = re.compile(r"^(Conc|GT\d)", re.I)
# 'GR<depth>x<width>' is also bar grating (1Wayne_Farms: GR1 1/4x36 at 5.45x), but other GR<n> families weigh as solid
# plates (ratio ~1): a GR piece counts as grating only when its solid is > 3x SDS2's (open-mesh) weight
GR_RX = re.compile(r"^GR\d", re.I)


def is_grating(t, ctx):
    s = t.get("section") or ""
    if NOT_STEEL_RX.match(s) and not s.lower().startswith("conc") or re.search(r"GRAT", s, re.I):
        return True
    if GR_RX.match(s):
        w = ctx.expected_weight(t)
        return bool(w and w > 0 and t["volume"] * STEEL_LB_PER_IN3 / w > 3)
    return False


def is_joist(t):
    return bool(JOIST_RX.match(t.get("section") or "")) or t.get("member_type") == "JOIST"


def m2_joists(ctx):
    r = Result("M2", "Open-web joists represented plausibly")
    J = [t for t in ctx.table if is_joist(t)]
    if not J:
        r.status, r.reason = "NA", "no joists in this model"; return r
    ratios = [t["volume"] * STEEL_LB_PER_IN3 / w for t in J for w in [ctx.expected_weight(t)] if w and w > 0]
    heavy = float(np.mean(np.array(ratios) > 3)) if ratios else None
    r.metrics = dict(joists=len(J), with_weight=len(ratios), median_mass_ratio=round(float(np.median(ratios)), 2) if ratios else None,
                     solid_block_share=round(heavy, 4) if heavy is not None else None)
    if heavy is None: r.status, r.reason = "WARN", "joists present but no recorded weight to judge them"
    elif heavy > 0.1: r.status, r.reason = "FAIL", "open-web joists written as solid blocks (EC-34): mass is 100x+ the real joist"
    else: r.status = "PASS"
    return r


def m1_mass(ctx):
    r = Result("M1", "Mass vs SDS2 recorded weight (rolled/plate steel)")
    ratios, fam = [], collections.defaultdict(list)
    skipped = collections.Counter()
    for t in ctx.table:
        if is_joist(t): continue          # judged separately by M2
        if NOT_STEEL_RX.match(t.get("section") or "") or (GR_RX.match(t.get("section") or "") and is_grating(t, ctx)):
            skipped["concrete / grating"] += 1; continue
        exp = ctx.expected_weight(t)
        if not exp or exp <= 0: continue
        q = t["volume"] * STEEL_LB_PER_IN3 / exp
        if 3.1 < q < 3.45:                # weighed by SDS2 as concrete (150 pcf = steel / 3.267), e.g. slabs not named Conc
            skipped["weighed as concrete"] += 1; continue
        ratios.append(q); fam[ctx.family_of(t)].append(q)
    if len(ratios) < 5:
        r.status, r.reason = "NA", "no recorded weights to compare"; return r
    a = np.array(ratios)
    within = float(np.mean(np.abs(a - 1) <= ctx.mass_tol))
    r.metrics = dict(compared=len(a), median_ratio=round(float(np.median(a)), 4), within_tol_share=round(within, 4), tol=ctx.mass_tol,
                     p05=round(float(np.percentile(a, 5)), 3), p95=round(float(np.percentile(a, 95)), 3),
                     by_family={k: (len(v), round(float(np.median(v)), 3)) for k, v in sorted(fam.items(), key=lambda kv: -len(kv[1]))[:8]},
                     not_compared=dict(skipped))
    # a whole family can be wrong while the model-wide median still looks fine (plate girders built from the
    # wrong fields came out at 0.39x on 50_Binney) - EC-41
    bad_fam = {k: (len(v), round(float(np.median(v)), 3)) for k, v in fam.items()
               if len(v) >= 20 and not (0.8 <= np.median(v) <= 1.25)}
    r.metrics["families_off"] = bad_fam
    med_ok = ctx.mass_median_band[0] <= np.median(a) <= ctx.mass_median_band[1]
    if bad_fam:
        # a whole section family built with the wrong profile is wrong geometry for every member of it, not a warning
        r.status = "FAIL"
        r.reason = f"section families with wrong mass: {', '.join(f'{k} ({v[0]} x{v[1]})' for k, v in bad_fam.items())} (EC-41 profile built from wrong fields)"
    elif med_ok and within >= ctx.mass_pass_share: r.status = "PASS"
    elif abs(np.median(a) - 1) < 0.5 and within >= getattr(ctx, "mass_warn_share", 0.5):
        r.status, r.reason = "WARN", "mass agreement weaker than expected"
    else: r.status, r.reason = "FAIL", "solid volumes disagree with SDS2 weights (EC-20 wrong section / EC-19 units / EC-21 lengths)"
    return r


# ======================================================================= G: internal geometry
def g1_workline(ctx):
    r = Result("G1", "Solid vs work line (length, top-of-steel, column axis)")
    if ctx.stage != "member":
        r.status, r.reason = "NA", "stage-2 pieces are cut to fabricated length; see E-checks"; return r
    ok_len, ok_tos, ok_col, n_len, n_tos, n_col = 0, 0, 0, 0, 0, 0
    ok_ctr = n_ctr = 0
    for t in ctx.table:
        m = ctx.member_by_id.get(t["member_id"])
        if not m or not m.section: continue
        p1, p2 = np.array(m.p1), np.array(m.p2); L = np.linalg.norm(p2 - p1)
        if L < 0.5: continue
        n_len += 1; ok_len += abs(t["obb"][0] - L) <= max(1.0, 0.01 * L)
        axis = (p2 - p1) / L
        # placement: solid centre must lie on the work line (within the section's half-diagonal) and at mid-span
        w = np.array(t["center"]) - (p1 + p2) / 2
        along = abs(w @ axis); perp = np.linalg.norm(w - (w @ axis) * axis)
        n_ctr += 1; ok_ctr += along <= 1.0 and perp <= 0.5 * math.hypot(m.section.d, max(m.section.bf, m.section.d)) + 0.5
        if m.type == "BEAM" and abs(axis[2]) < 0.02:
            n_tos += 1; ok_tos += abs(t["hi"][2] - max(p1[2], p2[2])) <= 0.25 + abs(math.sin(m.roll)) * m.section.bf
        if m.type == "COLUMN" and abs(axis[2]) > 0.999:
            n_col += 1; ok_col += np.linalg.norm(np.array(t["center"][:2]) - p1[:2]) <= 0.25
    s = lambda a, b: round(a / b, 4) if b else None
    r.metrics = dict(length_ok=s(ok_len, n_len), n_length=n_len, placed_on_workline=s(ok_ctr, n_ctr), top_of_steel_ok=s(ok_tos, n_tos),
                     n_level_beams=n_tos, column_axis_ok=s(ok_col, n_col), n_vertical_columns=n_col)
    vals = [v for v in (s(ok_len, n_len), s(ok_tos, n_tos), s(ok_col, n_col)) if v is not None]
    st1 = grade(min(vals) if vals else 0, lambda v: v >= 0.95, lambda v: v >= 0.8)
    # stage-1 placement is deterministic from the work line, so any displaced solid is a converter bug: strict bar
    st2 = grade(s(ok_ctr, n_ctr) or 0, lambda v: v >= 0.995, lambda v: v >= 0.97)
    r.status = worst([st1, st2])
    if r.status != "PASS": r.reason = "solids do not sit on their work lines (EC-22 TOS offset / EC-23 column reference axis / EC-21 length)"
    return r


def _aabb_grid(T, pad, cell=48.0):
    grid = collections.defaultdict(list)
    for i, t in enumerate(T):
        lo = np.floor((np.array(t["lo"]) - pad) / cell).astype(int); hi = np.floor((np.array(t["hi"]) + pad) / cell).astype(int)
        if np.prod(hi - lo + 1) > 4000:  # giant solid: index by its end cells only
            for c in (tuple(lo), tuple(hi)): grid[c].append(i)
            continue
        for x in range(lo[0], hi[0] + 1):
            for y in range(lo[1], hi[1] + 1):
                for z in range(lo[2], hi[2] + 1):
                    grid[(x, y, z)].append(i)
    return grid


def _touch(a, b, pad):
    return all(a["lo"][k] - pad <= b["hi"][k] and b["lo"][k] - pad <= a["hi"][k] for k in range(3))


def g2_connectivity(ctx):
    r = Result("G2", "Connectivity (solids touch neighbours)")
    T = ctx.table
    if len(T) < 5: r.status = "NA"; return r
    pad = 1.0
    grid = _aabb_grid(T, pad)
    touched = np.zeros(len(T), bool)
    for cellmembers in grid.values():
        if len(cellmembers) < 2: continue
        for ii, i in enumerate(cellmembers):
            if touched[i]: continue
            for j in cellmembers:
                if j != i and _touch(T[i], T[j], pad):
                    touched[i] = touched[j] = True; break
    share = float(touched.mean())
    r.metrics = dict(solids=len(T), touching_share=round(share, 4), isolated=int((~touched).sum()))
    r.status = grade(share, lambda v: v >= 0.9, lambda v: v >= 0.7)
    if r.status != "PASS": r.reason = "many solids float free of the structure (EC-24 placement / EC-15 stray)"
    return r


def g3_piece_parent(ctx):
    r = Result("G3", "Connection pieces sit on their parent member")
    if ctx.stage != "piece":
        r.status, r.reason = "NA", "stage-1 output has no connection pieces"; return r
    by_m = collections.defaultdict(list)
    for t in ctx.table: by_m[t["member_id"]].append(t)
    ok = n = 0
    off = []
    for mid, ts in by_m.items():
        if len(ts) < 2: continue
        main = max(ts, key=lambda t: t["volume"])
        for t in ts:
            if t is main: continue
            n += 1
            if _touch(t, main, 2.0) or any(_touch(t, u, 0.5) for u in ts if u is not t and u is not main):
                ok += 1
            else:
                off.append(t)
    if not n:
        r.status = "NA"; return r
    # An off-parent piece is not necessarily misplaced: SDS2 often lists connection material on the *other* member
    # of the connection (e.g. a shear tab owned by the beam but welded to the girder) - EC-44. Resolve with evidence:
    #   on_other_member : touches some other member's solid (within 0.5 in)
    #   ifc_confirmed   : SDS2's own IFC has a part in the same place (IoU >= 0.5 after alignment)
    idx = {id(t): i for i, t in enumerate(ctx.table)}
    grid = _aabb_grid(ctx.table, 0.5)
    def touches_other(t):
        lo = np.floor((np.array(t["lo"]) - 0.5) / 48.0).astype(int); hi = np.floor((np.array(t["hi"]) + 0.5) / 48.0).astype(int)
        seen = set()
        for x in range(lo[0], hi[0] + 1):
            for y in range(lo[1], hi[1] + 1):
                for z in range(lo[2], hi[2] + 1):
                    for j in grid.get((x, y, z), ()):
                        if j in seen: continue
                        seen.add(j); u = ctx.table[j]
                        if u["member_id"] != t["member_id"] and _touch(t, u, 0.5): return True
        return False
    other = [t for t in off if touches_other(t)]
    confirmed = None
    if ctx.ifc and off:
        from scipy.spatial import cKDTree
        E = [e for e in ctx.ifc["elements"] if e["kind"] in ("member", "part")]
        al = ctx.ifc_alignment or align_ifc(ctx.table, E)
        if al is not None:
            ctx.ifc_alignment = al
            EA = [_apply(e, al["R"], al["t"]) for e in E]
            tree = cKDTree(np.array([(np.array(e["lo"]) + e["hi"]) / 2 for e in EA]))
            confirmed = 0
            for t in off:
                _, ii = tree.query(t["center"], k=6)
                confirmed += any(_iou(t, EA[i]) >= 0.5 for i in np.atleast_1d(ii))
    raw = ok / n
    resolved = (ok + (confirmed if confirmed is not None else len(other))) / n
    r.metrics = dict(pieces_checked=n, on_parent_share=round(raw, 4), off_parent=len(off), off_parent_touching_other_member=len(other),
                     off_parent_confirmed_by_ifc=confirmed, resolved_share=round(resolved, 4),
                     basis="ifc" if confirmed is not None else "touching other member")
    r.status = grade(resolved, lambda v: v >= 0.95, lambda v: v >= 0.8)
    if r.status != "PASS":
        r.reason = "pieces placed away from their member and not confirmed elsewhere (EC-25 M vs M.T / EC-26 hole block read as material)"
    elif len(off):
        r.reason = f"{len(off)} pieces sit on another member of the connection (EC-44), accepted on {r.metrics['basis']} evidence"
    return r


def g4_duplicates(ctx):
    r = Result("G4", "Duplicate solids")
    groups = collections.defaultdict(list)
    for t in ctx.table:
        groups[(round(t["volume"], 2), *[round(v, 2) for v in t["lo"] + t["hi"]])].append(t)
    # members that are exact duplicates inside the SDS2 job itself (same type, section, work line) - EC-40
    twin = {}
    for m in ctx.members:
        twin[m.id] = (m.type, m.section.name if m.section else "", *np.round(np.r_[m.p1, m.p2], 2))
    d = src_d = 0
    ctx.dup_remove = []          # converter-made repeats (every copy after the first), for the dedup step
    for g in groups.values():
        if len(g) < 2: continue
        d += len(g) - 1
        # a repeat is the source's if every copy comes from a *different* member and those members are SDS2 twins
        mids = [t["member_id"] for t in g]
        keys = {twin.get(i) for i in mids}
        if len(set(mids)) == len(mids) and len(keys) == 1 and None not in keys:
            src_d += len(g) - 1
        else:
            ctx.dup_remove += sorted(g, key=lambda t: (t["member_id"] or 0, t.get("piece_id") or 0))[1:]
    extra = d - src_d
    share = extra / max(len(ctx.table), 1)
    r.metrics = dict(duplicates=d, already_in_sds2_job=src_d, introduced_by_converter=extra, share=round(share, 5))
    r.status = grade(share, lambda v: v <= 0.001, lambda v: v <= 0.01)
    if r.status != "PASS": r.reason = "identical solids written more than once (EC-27 header block + material block / EC-28 duplicate job copies)"
    elif src_d: r.reason = f"{src_d} duplicate members exist in the SDS2 job itself (kept as-is)"
    return r


def expected_piece_boxes(ctx):
    """Rebuild every placed piece's world bbox straight from the job (decoded vertices under the decoded block
    transform, origin + M.T @ v), independently of the STEP writer. Cached next to the STEP as <step>.expected.json."""
    import json
    cache = getattr(ctx, "step_path", "") + ".expected.json"
    if ctx.step_path and os.path.exists(cache) and os.path.getmtime(cache) > os.path.getmtime(ctx.step_path):
        raw = json.load(open(cache))
        return {tuple(map(int, k.split(":"))): v for k, v in raw.items()}
    from instances import material_instances, subm_vertices
    from piece_table import read_pieces
    pieces = read_pieces(ctx.job)
    out = collections.defaultdict(list)
    for mid in piece_member_ids(ctx):
        for sid, M, o in material_instances(ctx.job, mid, pieces)[1]:
            V = subm_vertices(ctx.job, sid)
            if V is None or len(V) < 4: continue
            # a few spurious vertex records (mis-aligned doubles) can lie hundreds of inches away (EC-45): in the
            # piece's local frame keep vertices within the section's own size of the median cross-section position
            # rolled pieces only: their cross-section (local y/z) is bounded by the section size. The spurious
            # points are hole/feature positions at bolt pitch (e.g. y = 427..445 in steps of 3 on a 17.5-in column).
            # Plates are NOT trimmed: their local frame varies (centred vs corner), so y/z can legitimately be large.
            p = pieces.get(sid, {}); sh = ctx.shapes.get(p.get("sec")) if p.get("sec") else None
            if sh is not None and sh.d > 0:
                size = max(sh.d, sh.bf)
                med = np.median(V, 0)
                keep = (np.abs(V[:, 1] - med[1]) <= size + 0.5) & (np.abs(V[:, 2] - med[2]) <= size + 0.5)
                if keep.sum() >= 4: V = V[keep]
            W = o + V @ M                     # row-vector form of o + M.T @ v
            out[(mid, sid)].append([W.min(0).tolist(), W.max(0).tolist()])
    if ctx.step_path:
        json.dump({f"{k[0]}:{k[1]}": v for k, v in out.items()}, open(cache, "w"))
    return out


def g5_piece_geometry(ctx):
    r = Result("G5", "Piece solids match decoded placement (independent rebuild)")
    if ctx.stage != "piece":
        r.status, r.reason = "NA", "stage-1 output; see G1"; return r
    if not hasattr(ctx, "_exp_boxes"):
        ctx._exp_boxes = expected_piece_boxes(ctx)
    E = ctx._exp_boxes
    n = nomatch = 0
    errs = []
    for t in ctx.table:
        if t["piece_id"] == 0:
            continue          # member envelope (no fabricated pieces to rebuild); judged by M2 / tier flags
        cands = E.get((t["member_id"], t["piece_id"]))
        n += 1
        if not cands:
            nomatch += 1; continue        # no vertex outline to rebuild from (e.g. weld studs): not a placement error
        lo, hi = np.array(t["lo"]), np.array(t["hi"])
        errs.append(min(max(np.abs(lo - c[0]).max(), np.abs(hi - c[1]).max()) for c in cands))
    a = np.array(errs)
    # Production pieces are exact B-reps (copes, cuts): smaller than the raw vertex box by up to a few inches, and
    # the vertex lists carry stray hole/feature points (EC-45). So exact agreement (0.1 in) is reported, and the
    # grade is on placement: within 3 in. Misplacements this check exists for are 6 in and more (self-test).
    # Calibrated on one production job (Greenwood 7.312: 72.6% within 0.1 in, 96.7% within 3 in, 6 of 2,317 > 12 in).
    tight = float(np.mean(a <= 0.1)) if len(a) else 0.0
    share = float(np.mean(a <= 3.0)) if len(a) else 0.0
    r.metrics = dict(solids=n, rebuilt=len(a), no_decoded_counterpart=nomatch, within_0_1in=round(tight, 4), within_3in=round(share, 4),
                     over_12in=int((a > 12).sum()) if len(a) else 0,
                     median_err_in=round(float(np.median(a)), 4) if len(a) else None, p99_err_in=round(float(np.percentile(a, 99)), 3) if len(a) else None)
    r.status = grade(share, lambda v: v >= 0.95, lambda v: v >= 0.85) if len(a) else "NA"
    if r.status not in ("PASS", "NA"): r.reason = "STEP piece solids differ from the decoded pieces (EC-24 placement / EC-20 wrong profile / EC-23 rotation / EC-43 writer error)"
    return r


# ======================================================================= E: external ground truth
def _iou(a, b, pad=0.25):
    lo = np.maximum(np.array(a["lo"]) - pad, np.array(b["lo"]) - pad); hi = np.minimum(np.array(a["hi"]) + pad, np.array(b["hi"]) + pad)
    inter = np.prod(np.clip(hi - lo, 0, None))
    va = np.prod(np.array(a["hi"]) - np.array(a["lo"]) + 2 * pad); vb = np.prod(np.array(b["hi"]) - np.array(b["lo"]) + 2 * pad)
    return float(inter / (va + vb - inter)) if inter > 0 else 0.0


def align_ifc(T, E, seed=0):
    """Estimate the IFC(site) -> job transform (rotation about z + translation), EC-29.
    Plan: 2D RANSAC on the xy centres of tall, thin elements (columns) - independent of member length, which
    differs legitimately between work-line solids and cut IFC pieces (EC-35). Height: mode of the top-of-steel
    difference between level beams that overlap in plan."""
    from scipy.spatial import cKDTree
    def ext(x): return np.array(x["hi"]) - np.array(x["lo"])
    def cols(S): return [x for x in S if ext(x)[2] > 60 and ext(x)[2] > 3 * max(ext(x)[:2])]
    ct_, ce_ = cols(T), cols(E)
    if len(ct_) < 4 or len(ce_) < 4: return None
    ct = np.unique(np.round([(np.array(t["lo"][:2]) + t["hi"][:2]) / 2 for t in ct_], 1), axis=0)
    ce = np.unique(np.round([(np.array(e["lo"][:2]) + e["hi"][:2]) / 2 for e in ce_], 1), axis=0)
    tree = cKDTree(ct); rng = random.Random(seed); best = (0, None)
    for _ in range(6000):
        i1, i2 = rng.randrange(len(ct)), rng.randrange(len(ct))
        dt = ct[i2] - ct[i1]; L = np.linalg.norm(dt)
        if L < 200: continue
        j1 = rng.randrange(len(ce))
        dd = np.linalg.norm(ce - ce[j1], axis=1)
        for j2 in np.where(np.abs(dd - L) < 1.0)[0][:8]:
            de = ce[j2] - ce[j1]
            th = math.atan2(dt[1], dt[0]) - math.atan2(de[1], de[0])
            R2 = np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]])
            t2 = ct[i1] - R2 @ ce[j1]
            d, _ = tree.query(ce @ R2.T + t2)
            sc = int((d < 1.0).sum())
            if sc > best[0]: best = (sc, (th, t2))
    if best[1] is None or best[0] < 4: return None
    th, t2 = best[1]
    R = np.array([[math.cos(th), -math.sin(th), 0], [math.sin(th), math.cos(th), 0], [0, 0, 1]])
    # height: level beams, top-of-steel difference to the nearest STEP beam in plan
    def level(S): return [x for x in S if ext(x)[2] < 0.3 * max(ext(x)[:2]) and max(ext(x)[:2]) > 60]
    lt, le = level(T), level(E)
    dz = 0.0
    if lt and le:
        tt = cKDTree(np.array([(np.array(t["lo"][:2]) + t["hi"][:2]) / 2 for t in lt]))
        diffs = []
        for e in le[:4000]:
            c = R[:2, :2] @ ((np.array(e["lo"][:2]) + e["hi"][:2]) / 2) + t2
            d, i = tt.query(c)
            if d < 6: diffs.append(lt[i]["hi"][2] - e["hi"][2])
        if diffs:
            h = collections.Counter(np.round(diffs, 0)); dz = float(h.most_common(1)[0][0])
            near = [x for x in diffs if abs(x - dz) < 1]; dz = float(np.median(near)) if near else dz
    return dict(R=R, t=np.array([t2[0], t2[1], dz]), inliers=best[0], of=len(ce))

def _apply(e, R, t):
    corners = np.array([[x, y, z] for x in (e["lo"][0], e["hi"][0]) for y in (e["lo"][1], e["hi"][1]) for z in (e["lo"][2], e["hi"][2])])
    c = corners @ R.T + t
    return dict(e, lo=c.min(0).tolist(), hi=c.max(0).tolist())


def e1_ifc(ctx):
    r = Result("E1", "SDS2 IFC export (aligned bbox IoU)")
    if not ctx.ifc:
        r.status, r.reason = "NA", "no IFC for this job"; return r
    from scipy.spatial import cKDTree
    want = ("member",) if ctx.stage == "member" else ("member", "part")
    E = [e for e in ctx.ifc["elements"] if e["kind"] in want]
    al = ctx.ifc_alignment or align_ifc(ctx.table, E)
    if al is None:
        r.status, r.reason = "FAIL", "could not align IFC to the STEP model (EC-29)"; return r
    ctx.ifc_alignment = al
    EA = [_apply(e, al["R"], al["t"]) for e in E]
    T = ctx.table
    ct = np.array(ctx.centers()); tree = cKDTree(ct)
    used = set(); hits = collections.Counter(); tot = collections.Counter()
    for e in EA:
        tot[e["kind"]] += 1
        c = (np.array(e["lo"]) + e["hi"]) / 2
        _, idx = tree.query(c, k=min(6, len(T)))
        for i in np.atleast_1d(idx):
            if i in used: continue
            if _iou(T[i], e) >= 0.5:
                used.add(i); hits[e["kind"]] += 1; break
    rec = {k: round(hits[k] / tot[k], 4) for k in tot}
    prec = round(len(used) / len(T), 4)
    r.metrics = dict(alignment_inliers=f'{al["inliers"]}/{al["of"]}', rotation_deg=round(math.degrees(math.atan2(al["R"][1][0], al["R"][0][0])), 4),
                     recall_by_kind=rec, precision=prec, ifc_elements=dict(tot))
    key = min(rec.values()) if rec else 0
    r.status = grade(key, lambda v: v >= 0.85, lambda v: v >= 0.6) if ctx.stage == "member" else grade(key, lambda v: v >= 0.7, lambda v: v >= 0.4)
    if r.status != "PASS": r.reason = "STEP solids do not coincide with SDS2's own export (EC-22/23/25 conventions, EC-30 missing pieces)"
    return r


def _multiset_match(truth, ours, tol_abs, tol_rel):
    """Greedy one-to-one match on (section, length). truth/ours: lists of (section, length, qty)."""
    pool = collections.defaultdict(list)
    for s, L, q in ours: pool[s] += [L] * q
    for s in pool: pool[s].sort()
    matched = total = 0
    miss = collections.Counter()
    for s, L, q in truth:
        for _ in range(q):
            total += 1
            arr = pool.get(s)
            if not arr:
                miss[(s, round(L, 1), "section absent")] += 1; continue
            tol = max(tol_abs, tol_rel * L)
            k = min(range(len(arr)), key=lambda i: abs(arr[i] - L))
            if abs(arr[k] - L) <= tol:
                matched += 1; arr.pop(k)
            else:
                miss[(s, round(L, 1), f"nearest {arr[k]:.1f}")] += 1
    return matched, total, [f"{s} L={L} x{c} ({why})" for (s, L, why), c in miss.most_common(8)]


def _bom_compare(ctx, truth):
    """truth: [(section, cut length, qty)]. Returns metrics + status.
    section_recall : qty-weighted share of truth whose section appears in the STEP (lengths ignored)
    tight_recall   : section + length within 0.25 in (fabricated cut length; required of stage-2 output)
    loose_recall   : section + length within max(12 in, 5%) (stage-1 draws members on their work line, which is
                     longer than the cut piece by the connection setbacks - EC-35)"""
    ours = _our_items(ctx)
    sec_only = [(s, 0.0, q) for s, L, q in truth]
    s_m, tot, s_miss = _multiset_match(sec_only, [(s, 0.0, 1) for s, L, _ in ours], 0.1, 0)
    t_m, _, t_miss = _multiset_match(truth, ours, 0.25, 0)
    l_m, _, l_miss = _multiset_match(truth, ours, 12.0, 0.05)
    # median (ours - truth) length over section matches, to expose systematic over-length
    pool = collections.defaultdict(list)
    for s, L, _ in ours: pool[s].append(L)
    diffs = [min(pool[s], key=lambda x: abs(x - L)) - L for s, L, q in truth if pool.get(s)]
    met = dict(compared_qty=tot, section_recall=round(s_m / tot, 4) if tot else None, tight_recall=round(t_m / tot, 4) if tot else None,
               loose_recall=round(l_m / tot, 4) if tot else None, median_excess_length_in=round(float(np.median(diffs)), 2) if diffs else None,
               unmatched_examples=(l_miss if ctx.stage == "member" else t_miss)[:6], section_absent=[m for m in s_miss if "absent" in m][:6])
    if not tot:
        return met, "NA"
    key = min(s_m, l_m) / tot if ctx.stage == "member" else t_m / tot
    return met, grade(key, lambda v: v >= 0.9, lambda v: v >= 0.7)


def _our_items(ctx):
    """(canonical section, length inches, qty 1) for every STEP solid."""
    from groundtruth import canon
    out = []
    for t in ctx.table:
        if ctx.stage == "member":
            m = ctx.member_by_id.get(t["member_id"])
            L = np.linalg.norm(np.subtract(m.p2, m.p1)) if m else t["obb"][0]
        else:
            L = t["obb"][0]
        out.append((canon(t["section"]), float(L), 1))
    return out


def e2_kiss(ctx):
    r = Result("E2", "KISS bill of materials")
    if not ctx.kiss:
        r.status, r.reason = "NA", "no KISS file"; return r
    member_types = {"BEAM", "COLUMN", "VERTICAL BRACE", "HORIZONTAL BRACE", "JOIST", "PL GIRDER", "BRACE", "GIRT", "PURLIN", "KICKER"}
    # KISS has one D line per piecemark with a quantity. Several KISS files (full ABM + fab packages) repeat the
    # same marks, so keep one line per mark (largest qty) - EC-33
    by_mark = {}
    for k in ctx.kiss:
        if k["mark"] not in by_mark or k["qty"] > by_mark[k["mark"]]["qty"]:
            by_mark[k["mark"]] = k
    rows = list(by_mark.values())
    if ctx.stage == "member":
        rows = [k for k in rows if k.get("kind") in member_types]
    truth = [(k["section"], k["length"], k["qty"]) for k in rows]
    met, r.status = _bom_compare(ctx, truth)
    r.metrics = dict(kiss_marks=len(rows), **met)
    if r.status == "NA": r.reason = "no comparable KISS lines"
    elif r.status != "PASS": r.reason = "sections/lengths in the STEP do not reproduce SDS2's bill of materials (EC-20/21/31/35)"
    return r


def e3_nc1(ctx):
    r = Result("E3", "DSTV NC1 parts")
    if not ctx.nc1:
        r.status, r.reason = "NA", "no NC1 files"; return r
    rolled = [p for p in ctx.nc1 if p["code"] in ("I", "U", "L", "M", "RO", "RU", "T")]
    truth = rolled if ctx.stage == "member" else ctx.nc1
    # stage 1 only knows main members: compare parts whose piecemark looks like a member mark (e.g. 1021B1)
    if ctx.stage == "member":
        truth = [p for p in truth if re.match(r"^\d+[A-Z]+\d*$", p["mark"])]
    # the same part appears in several fab packages (revisions / re-issues): one entry per piecemark - EC-33
    by_mark = {}
    for p in truth:
        by_mark.setdefault(p["mark"], p)
    truth = list(by_mark.values())
    met, r.status = _bom_compare(ctx, [(p["section"], p["length"], p["qty"]) for p in truth])
    r.metrics = dict(nc1_files=len(ctx.nc1), parts=len(truth), **met,
                     truth_holes=sum(p["holes"] * p["qty"] for p in truth), step_holes="not modelled yet (EC-32)")
    if r.status == "NA": r.reason = "no comparable NC1 parts"
    elif r.status != "PASS": r.reason = "fabrication parts (profile + cut length) not reproduced (EC-21/31/35)"
    return r


ALL = [d1_version_gate, d2_shape_table, d3_section_field, d4_geometry_fields, d5_outliers, d6_section_crosscheck,
       c1_completeness, s1_count, s2_validity, s3_names, s4_units_extent, m1_mass, m2_joists,
       g1_workline, g2_connectivity, g3_piece_parent, g4_duplicates, g5_piece_geometry, e1_ifc, e2_kiss, e3_nc1]
TABLE_CHECKS = [c1_completeness, s1_count, s2_validity, s3_names, s4_units_extent, m1_mass, m2_joists, g1_workline, g2_connectivity,
                g3_piece_parent, g4_duplicates, g5_piece_geometry, e1_ifc, e2_kiss, e3_nc1]



