"""Corpus tier for one verified SDS2 -> STEP file (verifier v1.3).

Two separate questions decide the tier:
  scope    - does the file carry connection pieces (stage 2) or members only (stage 1)?
  fidelity - is every solid exact, or are some of them stand-ins (flagged per part)?

  A               stage 2, no flagged parts, nothing missing (C1 PASS)
  A-unconfirmed   as A, but approximate pieces could not be told apart (flat file, no tags), so A cannot be certified
  B               stage 2 with flagged stand-ins, or up to 2% of pieces missing (C1 WARN; listed in _missing.csv)
  C-exact         stage 1 (members only), no flagged parts
  C-flagged       stage 1 with flagged stand-ins (in practice: open-web joists written as boxes)
  EXCLUDED        anything else; tier_reasons says why

tier_confidence: 'confirmed (outside evidence)', 'confirmed (internal checks)' or 'pending evidence'; see confidence().

Gaps every tier shares (no welds, no holes / copes yet) belong on the datasheet, not on each file.
Boxed joists (M2 FAIL) do not exclude a file: each one is counted as a joist_envelope part and the file drops
to B / C-flagged. Every other FAIL excludes it, and so does C1 FAIL (more than 2% missing).

Part flags. The production converter (batch/run_batch.py -> decode/to_step2.py) already marks its stand-ins, so
files converted before v1.3 need no re-run:
  bolt_guessed      bolt named "BOLT <d> x <grip> grip (nominal heavy hex)": no SDS2 bolt record covered that hole
                    stack (bolts from SDS2's records read "BOLT A325N 0.75 x 2.5 (grip 1.25)")
  joist_envelope    "(member envelope)" on a joist: member with no fabricated pieces written as its stage-1 box;
                    also any joist weighing > 3x SDS2's weight, or a 6-face box when no weight is recorded
  approx            "(member envelope)" on a non-joist; and in assembly files (the default) a piece written as a
                    standalone solid instead of an assembly component, since only exact B-rep pieces are shared
                    (fasteners and concrete, also standalone, are excluded by their manifest kind)
  grating_envelope  bar grating, piece names GT<n> (SDS2 weighs the open mesh; the converter writes a solid panel)
Converter tags are read too, in the solid name ("... (piece 40, approx)") or the manifest (<step>_pieces.csv: a
column named after the flag with a true value, or a flags / tags / note column listing them).
"""
import re, collections
import numpy as np
import checks as C
from steptable import parse_name

FLAGS = ("approx", "joist_envelope", "grating_envelope", "bolt_guessed")
# flags that lower the tier. Guessed (nominal) bolts are counted and reported for every file but don't lower it:
# almost every job has hundreds, and they are labelled per bolt in the STEP (decision 2026-10-02)
TIER_FLAGS = ("approx", "joist_envelope", "grating_envelope")
TRUTHY = {"1", "true", "yes", "y", "x"}
TAG_COLUMNS = ("flags", "tags", "flag", "tag", "note", "notes", "status")
# piece-table names that look like real SDS2 material; a misread table (other layouts) gives '?', '@', 'x3/8' ...
PIECE_NAME_OK = re.compile(r"^(W|M|S|HP|C|MC|L|LL|2L|WT|MT|ST|HSS|TS|PIPE|P|PL|FL|BAR|RD|SQ|RB|BLT|WS|GRAT|\d+(K|LH|DLH|G))", re.I)
VALIDATED = ("7.2", "7.3")     # versions whose decoding was proven against SDS2's own IFC (50 Binney, Greenwood)
GRATING_RX = re.compile(r"GRAT|^GT\d", re.I)
NOT_APPROX_KINDS = {"fastener", "concrete"}     # standalone by design in assembly files, not fallback pieces
# exact duplicate solids written by the converter (the same physical piece under two members; v4 notes: open issue)
# up to this share of solids are a flag (drop the repeats before use), above it the file is excluded
DUP_FLAG_MAX = 0.05
NOT_TIERED = {"CANNOT VERIFY": "job layout could not be decoded", "NOT CONVERTIBLE": "pre-conversion gate failed",
              "READY TO CONVERT": "no STEP given (pre-conversion gate only)"}


# v4 converter: _pieces.csv 'builder' says how each placed piece was built
BUILDER_TAGS = {"profile_fallback": "approx", "plate_fallback": "approx", "member_envelope": "member_envelope",
                "joist_envelope_approx": "joist_envelope"}          # exact_brep / special_primitive: no flag


def _manifest_tags(row):
    tags = {f for f in FLAGS if (row.get(f) or "").strip().lower() in TRUTHY}
    for c in TAG_COLUMNS:
        tags |= {w for w in re.split(r"[;|, ]+", (row.get(c) or "").lower()) if w in FLAGS}
    if row.get("builder") in BUILDER_TAGS:
        tags.add(BUILDER_TAGS[row["builder"]])
    return tags


def merge_manifest_tags(ctx):
    """Copy part tags recorded in the converter manifest onto the matching solids, so a tag counts whether the
    converter wrote it in the solid name or in the manifest CSV. Matched on member id (stage 1) or member + piece id,
    and the instance number when both sides have one (stage 2). Returns the number of solids that gained a tag."""
    for t in ctx.table:
        if "tags" not in t:                     # tables cached by v1.1 and earlier
            t["tags"] = parse_name(t["name"])["tags"]
    pending = collections.defaultdict(list)
    for r in getattr(ctx, "manifest_rows", None) or []:
        tags = _manifest_tags(r)
        if not tags or r.get("solid", "1") != "1":
            continue
        try:
            key = (int(r.get("id") or r["member"]),) if ctx.stage == "member" else (int(r["member"]), int(r["piece"]))
        except (KeyError, TypeError, ValueError):
            continue
        pending[key].append((int(r["inst"]) if (r.get("inst") or "").isdigit() else None, tags))
    n = 0
    for t in ctx.table:
        if t["member_id"] is None:
            continue
        lst = pending.get((t["member_id"],) if ctx.stage == "member" else (t["member_id"], t["piece_id"]))
        if not lst:
            continue
        i = next((k for k, (inst, _) in enumerate(lst) if inst is not None and inst == t.get("inst")), 0)
        new = lst.pop(i)[1] - set(t["tags"])
        if new:
            t["tags"] = list(t["tags"]) + sorted(new); n += 1
        t["approx"] = t.get("approx") or "approx" in t["tags"]
    return n


def piece_table(ctx):
    """The SDS2 job's piece table, or None when it is missing or misread. The reader knows the 7.2xx layout; on
    other versions it returns garbage names, which must not be counted as plates or grating."""
    if not hasattr(ctx, "_piece_table"):
        P = None
        try:
            from piece_table import read_pieces
            P = read_pieces(ctx.job) or None
        except Exception:
            pass
        if P and np.mean([bool(PIECE_NAME_OK.match(p["name"])) for p in P.values()]) < 0.8:
            P = None
        ctx._piece_table = P
    return ctx._piece_table


def part_flags(ctx):
    """Solid counts per flag (bolts included), the number of flagged solids, and why A cannot be certified (or None)."""
    n = collections.Counter()
    P = piece_table(ctx) if ctx.stage == "piece" else None
    assembly = getattr(ctx, "assembly_mode", False)
    # v4 manifests say how each piece was built: authoritative, so the standalone-solid rule is not needed
    builder = any("builder" in r for r in (getattr(ctx, "manifest_rows", None) or [])[:1])
    special = {(int(r["member"]), int(r["piece"])) for r in getattr(ctx, "manifest_rows", None) or []
               if r.get("kind") in NOT_APPROX_KINDS and (r.get("member") or "").isdigit() and (r.get("piece") or "").isdigit()}
    approx_tagged = False
    for t in ctx.table:
        tags = set(t["tags"])
        approx_tagged |= "approx" in tags
        if "member_envelope" in tags:
            tags.add("joist_envelope" if C.is_joist(t) else "approx")
        elif C.is_joist(t) and "joist_envelope" not in tags:
            w = ctx.expected_weight(t)
            if (w and w > 0 and t["volume"] * C.STEEL_LB_PER_IN3 / w > 3) or (not w and t.get("faces", 0) <= 6):
                tags.add("joist_envelope")
        if assembly and not builder and t["stage"] == "piece" and not t.get("in_assembly") and t.get("piece_id") \
                and (t["member_id"], t["piece_id"]) not in special and not C.NOT_STEEL_RX.match(t.get("section") or ""):
            tags.add("approx")       # standalone piece in an assembly file: built by a fallback, not from its B-rep
        names = [t.get("section") or "", t.get("member_type") or ""]
        if P and t.get("piece_id") in P:
            names.append(P[t["piece_id"]]["name"])
        if any(GRATING_RX.search(s) for s in names) or (C.GR_RX.match(t.get("section") or "") and C.is_grating(t, ctx)):
            tags.add("grating_envelope")
        for f in FLAGS:
            n[f] += f in tags
        n["flagged_solids"] += bool(tags & set(TIER_FLAGS))
    for b in getattr(ctx, "bolts", []):
        n["bolt_guessed"] += "bolt_guessed" in b["tags"]
    unconfirmed = None
    if ctx.stage == "piece" and not assembly and not builder and not approx_tagged:
        unconfirmed = "flat file without approx tags: approximate pieces cannot be told apart from exact ones"
    return {k: n[k] for k in FLAGS + ("flagged_solids",)}, unconfirmed


def source_connections(ctx):
    """Connection plates/bars in the SDS2 job's piece table: tells 'never detailed' apart from 'not converted'.
    None when the piece table is missing or could not be read reliably for this version."""
    from piece_table import kind
    P = piece_table(ctx)
    return None if P is None else sum(1 for p in P.values() if kind(p) == "plate")


CONF_EXTERNAL = "confirmed (outside evidence)"
CONF_INTERNAL = "confirmed (internal checks)"
CONF_PENDING = "pending evidence"


def confidence(stage, version, evidence, statuses=None):
    """How far the tier can be trusted (decision 2026-10-02: three levels, nothing hidden):
      confirmed (outside evidence)  SDS2's own IFC / KISS / NC1 agree with the file (an E-check passed)
      confirmed (internal checks)   stage 1: a validated version (7.2/7.3) with SDS2's weights agreeing;
                                    stage 2: every expected piece present (C1 PASS/WARN), every piece's weight
                                    agreeing with SDS2's (M1 PASS) and placements rebuilt (G5 PASS/WARN).
                                    Limit: parts the shared piece decoder never sees can't be caught this way
                                    (Greenwood: ~950 studs found only by KISS / NC1)
      pending evidence              neither"""
    st = statuses or {}
    if evidence == "external":
        return CONF_EXTERNAL
    validated = (version or "").startswith(VALIDATED)
    if stage == "member" and validated and evidence == "mass":
        return CONF_INTERNAL
    if stage == "piece" and st.get("C1") in ("PASS", "WARN") and st.get("M1") == "PASS" and st.get("G5") in ("PASS", "WARN"):
        return CONF_INTERNAL
    return CONF_PENDING


def assign(verdict, stage, statuses, flags, unconfirmed, solids, source_plates=None):
    """Pure rule, so it can be replayed on stored reports. Returns dict(tier, tier_reasons)."""
    why = []
    if verdict in NOT_TIERED:
        return dict(tier="EXCLUDED", tier_reasons=[NOT_TIERED[verdict]])
    # stage 2: member-decoder checks (the verifier's reading of the member index) don't judge piece geometry
    soft = {"C1", "M2", "G4"} | ({"D1", "D2", "D3", "D4", "D5", "D6"} if stage == "piece" else set())
    hard = sorted(k for k, v in statuses.items() if v == "FAIL" and k not in soft)
    if hard:
        return dict(tier="EXCLUDED", tier_reasons=[f"checks failed: {' '.join(hard)}"])
    if statuses.get("C1") == "FAIL":
        return dict(tier="EXCLUDED", tier_reasons=["more than 2% of expected items missing (C1 FAIL)"])
    if statuses.get("M2") == "FAIL" and not flags.get("joist_envelope"):
        return dict(tier="EXCLUDED", tier_reasons=["M2 FAIL but no joist could be identified to flag"])
    dups = flags.get("duplicates_by_converter") or 0
    if statuses.get("G4") == "FAIL" and dups / max(1, solids) > DUP_FLAG_MAX:
        return dict(tier="EXCLUDED", tier_reasons=[f"{dups} duplicate solids written by the converter ({dups / max(1, solids):.1%} > {DUP_FLAG_MAX:.0%})"])
    # converter duplicates are removed in the dedup copy (verify.py --dedup-out), which is the file to ship, so they
    # don't lower the tier (decision 2026-10-02); above DUP_FLAG_MAX the file is excluded instead (see above)
    flagged = flags.get("flagged_solids", 0)
    if flagged:
        why.append(f"{flagged} of {solids} solids flagged (" + ", ".join(f"{k} {v}" for k, v in flags.items() if k in TIER_FLAGS and v) + ")")
    if flags.get("bolt_guessed"):
        why.append(f"{flags['bolt_guessed']} guessed bolts (nominal heavy hex, labelled in the STEP; don't lower the tier)")
    if dups:
        why.append(f"{dups} exact duplicate solids written by the converter: ship the de-duplicated copy (--dedup-out), "
                   f"not the original (G4)")
    if stage == "piece" and any(statuses.get(k) == "FAIL" for k in ("D1", "D2", "D3", "D4", "D5", "D6")):
        why.append("verifier's member decoder is unreliable for this job (D-checks); piece checks decide")
    if stage == "piece":
        if statuses.get("C1") == "WARN":
            why.append("up to 2% of expected pieces missing or unexpected (C1 WARN, see _missing.csv)")
        if flagged or statuses.get("C1") == "WARN":
            tier = "B"
        elif unconfirmed:
            tier = "A-unconfirmed"
            why.append(unconfirmed)
        else:
            tier = "A"
    elif stage == "member":
        tier = "C-flagged" if flagged else "C-exact"
        if statuses.get("C1") == "WARN":
            why.append("up to 2% of expected members missing or unexpected (C1 WARN, see _missing.csv)")
        if source_plates:
            why.append(f"source job has {source_plates} connection plates that are not in this file (stage-2 candidate)")
        elif source_plates == 0:
            why.append("source job has no connection plates (members-only model)")
    else:
        return dict(tier="EXCLUDED", tier_reasons=["solid names do not say whether this is stage 1 or stage 2"])
    return dict(tier=tier, tier_reasons=why)


def tier_for(ctx, results, verdict, evidence):
    statuses = {r.id: r.status for r in results}
    c1 = next((r for r in results if r.id == "C1"), None)
    if ctx.stage == "piece" and c1 is not None and not c1.metrics.get("expected_pieces"):
        statuses["C1"] = "NA"          # nothing decodable to check completeness against: never 'confirmed'
    if verdict in NOT_TIERED or not getattr(ctx, "table", None):
        return dict(assign(verdict, ctx.stage, statuses, {}, None, 0), tier_confidence=None, flags={}, assembly_file=None,
                    source_connection_plates=None)
    flags, unconfirmed = part_flags(ctx)
    g4 = next((r for r in results if r.id == "G4"), None)
    flags["duplicates_by_converter"] = int((g4.metrics.get("introduced_by_converter") or 0) if g4 else 0)
    plates = source_connections(ctx) if ctx.stage == "member" else None
    solids = len(ctx.table) + len(getattr(ctx, "bolts", []))
    out = assign(verdict, ctx.stage, statuses, flags, unconfirmed, solids, plates)
    if ctx.stage == "member" and plates is None:
        out["tier_reasons"].append("could not tell whether the source job has connection plates (piece table unreadable for this version)")
    conf = None if out["tier"] == "EXCLUDED" else confidence(ctx.stage, ctx.version, evidence, statuses)
    return dict(out, tier_confidence=conf, flags=flags, flagged_share=round(flags["flagged_solids"] / max(1, solids), 5),
                assembly_file=getattr(ctx, "assembly_mode", False), bolts=len(getattr(ctx, "bolts", [])),
                manifest_tagged_solids=getattr(ctx, "manifest_tagged", 0),
                manifest_columns=list((getattr(ctx, "manifest_rows", None) or [{}])[0].keys()), source_connection_plates=plates)
