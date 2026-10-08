"""Per-job manifest (sidecar JSON) for an SDS2 -> STEP conversion: what was written, what is a stand-in and why,
what was skipped, the weight check against SDS2, and a proposed class / corpus tag.

Class / corpus (proposed; the thresholds are in classify() and the inputs are all in the manifest, so a builder can
re-grade without re-converting):
  class 1 / corpus A  complete: every fabricated piece is SDS2's own exact geometry, no stand-ins, nothing skipped,
                      steel within 0.9-1.1 of SDS2's piece weights (when the job has weights)
  class 2 / corpus B  complete model with tagged stand-ins: joists as open-web representatives or envelopes, grating
                      as its solid panel, guessed (nominal) bolts, approximate pieces without copes / holes; every such
                      part carries "[approx: ...]" in its STEP name and is listed under "standins"
  class 3 / corpus C  members only: no fabricated pieces could be written (member envelopes / joist stand-ins only),
                      or an empty job (no member files; proof in class_reasons)
  corpus R            reference / imported geometry only (DWF / IFC import members): class 1 or 2 by fidelity
  class 0 / broken    conversion failed, STEP solids invalid after read-back, steel outside 0.75-1.3 of SDS2, or
                      more than 5 % of the placed pieces not built
"""
import json, re, collections, os

SCHEMA = "sds2-step-manifest/v5"
CLASS1_TOLERATED = set()   # owner rule: any approximation (incl. designation-derived joists, weight-sized built-up
                           # sections, concrete prisms) keeps a job out of class 1
NEEDED = {  # what the source would need for the part to be exact
    "joist_openweb_standin": "the vendor joist design (chord / web sizes, panel points, seats); SDS2 holds only the designation",
    "joist_envelope_box": "the vendor joist design; SDS2 holds only the designation",
    "member_envelope": "fabricated pieces for the member (cut length, copes, holes); the job has only its work line and section",
    "nominal_bolt": "an SDS2 bolt record (length, head side, washers)",
    "rolled_profile_extrusion": "a readable SDS2 piece B-rep (copes, cuts, end preparation)",
    "plate_from_vertices": "a readable SDS2 piece B-rep (cut outline, bends)",
    "piece_table_standin": "readable piece geometry (only the piece-table L x W x T / section is known)",
    "grating_solid_panel": "grating bars and bands stored as faces that bound closed solids, with the cross bar fields in "
                           "the piece record (the reason names what this piece lacks)",
    "holes_not_cut": "a successful boolean of the decoded holes",
    "concrete_prism": "the concrete mesh as a closed solid",
    "builtup_estimated": "the real built-up section dimensions (flange widths / thicknesses)",
    "mesh_cylinder": "the fastener mesh as a closed solid",
    "holes_derived_from_bolts": "SDS2 hole records for the main material (NC hole data)",
    "mating_holes_not_stored": "hole records for the main member (SDS2 keeps them only for NC output)",
    "brep_unvalidated": "a readable piece-table entry (weight / size) to check SDS2's stored B-rep against",
    "grating_crossbars_from_record": "the cross bars as solids (SDS2 stores each as a flat outline plus the depth in the grating record)",
    "brep_open_surface": "the piece's end / missing faces (SDS2 stores the body with open rims; written open, not filled)",
    "holes_from_nc1": "the hole records in SDS2's piece file (these holes come from the job's own NC1 output)",
}


def family(name):
    n = (name or "").strip()
    if n.startswith("BPL"): return "BPL"
    if n.startswith("PIPE"): return "ROUND"
    if n.startswith("HSS"): return "ROUND" if n.lower().count("x") == 1 else "HSS"
    m = re.match(r"[A-Z]+", n)
    return m.group() if m else "?"


def classify(m):
    """-> (class, corpus, reasons) from a manifest dict (pre- or post-read-back)."""
    c = m["counts"]; w = m.get("weight_check") or {}; rb = m.get("readback") or {}
    reasons = []
    ratio = w.get("ratio")
    if w.get("dominant_outliers") and w.get("ratio_without_outliers") is not None:
        reasons.append("steel ratio {} with {} dominant piece(s) whose SDS2 weight disagrees with their geometry "
                       "({}); {} without them".format(ratio, len(w["dominant_outliers"]),
                                                      ", ".join(o["name"] for o in w["dominant_outliers"][:3]),
                                                      w["ratio_without_outliers"]))
        ratio = w["ratio_without_outliers"]
    broken = []
    if not m.get("write_ok", True):
        broken.append("STEP write failed")
    if c.get("solids_written", 0) == 0:
        # nothing could be written: class 3 with proof when the source holds nothing placeable
        if c.get("reference_members") and not c.get("reference_placements"):
            return 3, "R", [f"imported reference model whose {c.get('reference_unlinked_frames', 0)} placement blocks carry a GUID and "
                            "colour but no piece id (piece link absent from the stored data): nothing can be placed"]
        if not c.get("placed_pieces") and not c.get("reference_members"):
            return 3, "C", [f"no geometry in the source: {c.get('members', 0)} member(s), none with a section or fabricated "
                            f"pieces ({c.get('members_without_geometry', 0)} without geometry), 0 placed pieces (seed / empty job)"]
        broken.append("no solids written")
    if rb.get("checked") and rb.get("invalid", 0) > 0:
        broken.append(f"{rb['invalid']} solid(s) invalid after STEP read-back")
    if rb.get("checked") and rb.get("load_errors", 0) > 0:
        broken.append(f"{rb['load_errors']} STEP syntax / reference errors on read-back")
    if ratio is not None and not 0.75 <= ratio <= 1.3:
        broken.append(f"steel {ratio:.3f}x SDS2's piece weights (outside 0.75-1.3)")
    # members whose stored end points are unusable have no pieces either: listed, not counted as placed pieces lost
    # pieces whose piece file is absent from the job (source data absent, v5.5.7) are named, not a converter failure
    steel_skipped = c.get("skipped", 0) - c.get("reference_skipped", 0) - c.get("members_end_points_unusable", 0) \
        - c.get("pieces_without_piece_file", 0)
    placed = max(c.get("placed_pieces", 0) - c.get("reference_parts", 0) - c.get("reference_skipped", 0), 1)
    if steel_skipped > 0.05 * placed and c.get("placed_pieces", 0) > 0:
        broken.append(f"{steel_skipped} of {placed} placed steel pieces not built (> 5 %)")
    if broken:
        return 0, "broken", broken + reasons
    if c.get("pieces_written", 0) == 0 and c.get("reference_parts", 0) > 0:
        # corpus R = reference / imported geometry (DWF / IFC import members), graded by fidelity like steel jobs
        st = dict(m["standins"]["by_type"])
        r = [f"reference model: {c['reference_parts']} parts of an imported model written from SDS2's stored B-rep "
             "(not SDS2-modelled steel)"]
        if c.get("reference_open_shells"):
            r.append(f"{c['reference_open_shells']} parts are open surfaces as stored (not closed solids)")
        if c.get("skipped"):
            r.append(f"{c['skipped']} placed parts not written")
        if c.get("reference_open_shells") and not c.get("skipped") and not st:
            return 2, "R", r
        if st:
            r.append("stand-ins: " + ", ".join(f"{v} {k}" for k, v in st.items()))
        return (2 if (c.get("skipped") or st) else 1), "R", r
    if c.get("pieces_written", 0) == 0:
        return 3, "C", ["no fabricated pieces in the job: members only"
                        + (f" ({c.get('joist_standins', 0)} joist stand-ins, {c.get('member_envelopes', 0)} envelopes)")]
    st = dict(m["standins"]["by_type"])
    minor = {k: st.pop(k) for k in list(st) if k in CLASS1_TOLERATED}
    if minor:
        reasons.append("tolerated for class 1: " + ", ".join(f"{v} {k}" for k, v in minor.items()))
    n_st = sum(st.values())
    if n_st:
        reasons.append("stand-ins: " + ", ".join(f"{v} {k}" for k, v in sorted(st.items(), key=lambda kv: -kv[1])))
    if c.get("invalid_parts_excluded"):
        reasons.append(f"{c['invalid_parts_excluded']} part(s) left out because they read back invalid "
                       "(listed under skipped, reason exact_solid_invalid_at_placement)")
    if c.get("skipped"):
        reasons.append(f"{c['skipped']} placed pieces not built"
                       + (f" ({c['pieces_without_piece_file']} have no piece file in the job: source data absent)"
                          if c.get("pieces_without_piece_file") else ""))
    if ratio is not None and not 0.9 <= ratio <= 1.1:
        reasons.append(f"steel {ratio:.3f}x SDS2's piece weights (outside 0.9-1.1)")
    if ratio is None:
        reasons.append("no SDS2 piece weights to check against")
    if n_st or c.get("skipped") or (ratio is not None and not 0.9 <= ratio <= 1.1) or w.get("dominant_outliers"):
        return 2, "B", reasons
    return 1, "A", reasons or ["all pieces exact SDS2 geometry; steel within 10 % of SDS2"]


def _standin_type(r):
    b = r.get("builder", ""); s = r.get("standin", "")
    if "built-up" in s and b != "joist_openweb_standin": return "builtup_estimated"
    if b == "joist_openweb_standin": return "joist_openweb_standin"
    if b in ("joist_envelope_approx",): return "joist_envelope_box"
    if b == "member_envelope": return "member_envelope"
    if b == "grating_from_record": return "grating_crossbars_from_record"
    if "grating" in s: return "grating_solid_panel"
    if "holes decoded but not cut" in s and b == "exact_brep": return "holes_not_cut"
    if b == "exact_brep_unvalidated": return "brep_unvalidated"
    if "open surface as stored by SDS2" in s and b == "exact_brep": return "brep_open_surface"
    if "holes_from_nc1" in s and b == "exact_brep": return "holes_from_nc1"
    if b == "piece_table_standin": return "piece_table_standin"
    if b in ("profile_fallback", "vertex_box_fallback"): return "rolled_profile_extrusion"
    if b in ("plate_fallback", "plate_hull_fallback", "bent_plate_fallback"): return "plate_from_vertices"
    if b == "special_primitive": return "concrete_prism" if "concrete" in s else "mesh_cylinder"
    if "built-up" in s: return "builtup_estimated"
    return b or "other"


def _outliers(piece_dev, step_lb, sds2_lb):
    """Single pieces that dominate the job's steel tally (|deviation| > 25 % of SDS2's total): e.g. DOWCORNING 7.039
    BPL240x240 recorded at 447,816 lb of 549,800 lb. Returned for listing; the class ratio is computed without them."""
    out = []
    if sds2_lb <= 0:
        return out, None
    agg = collections.defaultdict(lambda: [0.0, 0.0, "", 0])
    for d, w, name, sid in piece_dev:
        a = agg[sid]; a[0] += d; a[1] += w; a[2] = name; a[3] += 1
    for sid, (d, w, name, cnt) in agg.items():
        if abs(d) > 0.25 * sds2_lb:
            out.append(dict(piece=sid, name=name, instances=cnt, sds2_lb=round(w, 1), step_lb=round(w + d, 1)))
    if not out:
        return out, None
    s_ = sum(o["step_lb"] for o in out); w_ = sum(o["sds2_lb"] for o in out)
    return out, (round((step_lb - s_) / (sds2_lb - w_), 4) if sds2_lb - w_ > 0 else None)


def build(job, out, version, stats, rows, skipped, dups, bolt_standins, mems, placed, members_without_geometry,
          weights, holes, write_ok, piece_dev=()):
    st_rows = [r for r in rows if r.get("standin")]
    groups = collections.OrderedDict()
    for r in st_rows:
        t = _standin_type(r)
        g = groups.setdefault((t, r.get("real_type") or r["name"]), dict(type=t, real_type=r.get("real_type") or r["name"],
                                                                          reason=r["standin"], needed=NEEDED.get(t, ""),
                                                                          count=0, parts=[]))
        g["count"] += 1; g["parts"].append(r.get("label") or r["name"])
    if bolt_standins:
        groups[("nominal_bolt", "bolt")] = dict(type="nominal_bolt", real_type="structural bolt (assembly) at a decoded hole stack",
                                                reason="no SDS2 bolt record covers this hole stack: heavy-hex bolt with the stack's "
                                                       "diameter and grip; length, head side and washers guessed",
                                                needed=NEEDED["nominal_bolt"], count=len(bolt_standins), parts=bolt_standins)
    der = (holes or {}).get("derived") or {}
    if der.get("pieces"):
        groups[("holes_derived_from_bolts", "holes")] = dict(
            type="holes_derived_from_bolts", real_type="bolt holes in the main material",
            reason="derived: bolt record + coaxial hole (SDS2 stores no hole record for these pieces)",
            needed=NEEDED["holes_derived_from_bolts"], count=der["pieces"],
            parts=[f"piece {k}: {v} hole(s)" for k, v in sorted(der.get("by_piece", {}).items(), key=lambda kv: -kv[1])])
    nc = ((holes or {}).get("holes_not_cut") or {}).get("by_reason") or {}
    single = sum(v for k, v in nc.items() if k.startswith("decoded hole with no bolt"))
    if single:
        groups[("mating_holes_not_stored", "holes")] = dict(
            type="mating_holes_not_stored", real_type="bolt holes in the piece a single decoded ply bolts to",
            reason="decoded hole with no bolt record or >= 2-ply stack: the adjoining piece's hole is not in the data "
                   "and is not extended into it (rule)",
            needed=NEEDED["mating_holes_not_stored"], count=single, parts=[])
    by_type = collections.Counter()
    for g in groups.values():
        by_type[g["type"]] += g["count"]
    ref_rows = [r for r in rows if r.get("builder") == "reference_brep"]
    pieces_rows = [r for r in rows if r.get("piece") and r.get("builder") != "reference_brep"]
    exact = sum(1 for r in pieces_rows if r.get("builder") == "exact_brep")
    sds2_t = weights["sds2_lb"] / 2000; step_t = weights["step_lb"] / 2000
    counts = dict(members=len(mems), members_structural=sum(1 for m in mems if m.type not in ("Ref Point",)),
                  members_with_pieces=len({r["member"] for r in pieces_rows}),
                  members_without_geometry=members_without_geometry,
                  placed_pieces=placed, pieces_written=len(pieces_rows), pieces_exact=exact,
                  pieces_approx=len(pieces_rows) - exact,
                  reference_members=stats.get("reference_members", 0), reference_placements=stats.get("reference_placements", 0),
                  reference_unlinked_frames=stats.get("reference_unlinked_frames", 0),
                  reference_parts=len(ref_rows), reference_open_shells=stats.get("reference_open_shells", 0),
                  reference_face_sets=stats.get("reference_face_sets", 0),
                  reference_skipped=sum(1 for x in skipped if x.get("kind") == "reference"),
                  members_end_points_unusable=sum(1 for x in skipped if x.get("reason") == "member_end_points_unusable"),
                  pieces_without_piece_file=sum(1 for x in skipped if x.get("reason") == "no_piece_file"),
                  invalid_parts_excluded=sum(1 for x in skipped if x.get("reason") == "exact_solid_invalid_at_placement"),
                  member_envelopes=sum(1 for r in rows if not r.get("piece") and r.get("builder") != "joist_openweb_standin"),
                  joist_standins=sum(1 for r in rows if r.get("builder") == "joist_openweb_standin"),
                  pieces_validated_by_section=stats.get("validated_by_section", 0),
                  holes_from_nc1=stats.get("holes_from_nc1", 0),
                  nc1_opt_in=stats.get("nc1"),
                  bolts_sds2=stats.get("bolts_sds2", 0), bolts_nominal=stats.get("bolts_nominal", 0),
                  bolts_on_stored_hardware=dict(sds2=stats.get("bolts_on_stored_hardware_sds2", 0),
                                                nominal=stats.get("bolts_on_stored_hardware_nominal", 0)),
                  solids_written=len(rows) + stats.get("bolts", 0),
                  skipped=len(skipped), converter_duplicates_skipped=len(dups),
                  unique_parts=stats.get("unique_parts"), parts_written_flat=stats.get("parts_written_flat"))
    skip_reasons = collections.Counter(s["reason"] for s in skipped)
    outl, ratio_ex = _outliers(piece_dev, weights["step_lb"], weights["sds2_lb"])
    man = dict(schema=SCHEMA, converter="sds2-step-pipeline v5", job=os.path.basename(job.rstrip("/\\")), version=version,
               stage=2, step=os.path.basename(out), write_ok=bool(write_ok), counts=counts,
               weight_check=dict(sds2_piece_weight_t=round(sds2_t, 2), step_steel_t=round(step_t, 2),
                                 ratio=round(step_t / sds2_t, 4) if sds2_t > 0 else None,
                                 joist_standin_t=round(weights.get("joist_standin_lb", 0) / 2000, 2),
                                 dominant_outliers=outl, ratio_without_outliers=ratio_ex,
                                 note="steel pieces only: concrete, grating panels and member envelopes are excluded; "
                                      "joist stand-ins are sized to typical joist weights (not SDS2 data)",
                                 by_family=weights.get("by_family")),
               holes=holes,
               standins=dict(total=sum(by_type.values()), by_type=dict(by_type),
                             share_of_solids=round(sum(by_type.values()) / max(counts["solids_written"], 1), 4),
                             groups=list(groups.values())),
               skipped=dict(total=len(skipped), by_reason=dict(skip_reasons),
                            parts=[{k: s[k] for k in ("member", "member_type", "piece", "inst", "name", "kind", "reason")} for s in skipped]),
               converter_duplicates=dict(total=len(dups), parts=dups[:5000]),
               readback=dict(checked=False))
    for k in ("grating", "rods"):                  # [sgc] patch sds2-grating-cylinders: builder outcome sections
        if stats.get("sgc_" + k):
            man[k] = stats["sgc_" + k]
    man["class"], man["corpus"], man["class_reasons"] = classify(man)
    return man


def write(man, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))


def update_readback(path, rb, checked=True):
    """Merge the --verify read-back result into an existing manifest and re-classify (checked=False: the read-back was
    stopped by its time budget; the STEP is kept and graded without it)."""
    if not os.path.exists(path):
        return None
    man = json.load(open(path, encoding="utf-8"))
    man["readback"] = dict(rb, checked=checked)
    man["class"], man["corpus"], man["class_reasons"] = classify(man)
    write(man, path)
    return man
