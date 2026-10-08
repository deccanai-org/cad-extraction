"""Apply the joist / envelope / type-slot fixes to an sds2-step-pipeline v5.x tree (built and tested on v5.2,
sds2-step-pipeline-v5.2.zip sha256 f2d05d38...). Anchored string replacements, so it survives unrelated edits; every
anchor must match exactly once or the script stops without writing anything.

usage: python apply_v5_patch.py <sds2-step-pipeline dir>
  also copy patch/decode/joist_catalog.py and joist_catalog.json into <dir>/decode/
"""
import os, sys

EDITS = {}

# ---------------------------------------------------------------- sds2job.py: member type read from the right slot
EDITS["decode/sds2job.py"] = [
("""def read_members(job, layout=None):""",
'''_JOIST_SEC = re.compile(r"^\\d+(?:\\.\\d+)?(?:KCS|K|LH|DLH|SLH)", re.I)


def _type_shift(idx, slot, toff, recs, fw):
    """Slot holding member n's type string: n (7.2+ f64 families) or n + 1 (f32 families: 1280-B 6.3xx/7.0xx and 1416-B
    7.1xx slots store the type at the start of the NEXT slot). Reading slot n there mislabels ~9 % of members
    (BAHAMAR 7.135: 406 of 4,471 - JOISTs typed BEAM/COLUMN/MISC, beams typed JOIST/COLUMN). Chosen by consistency:
    JOIST <-> joist designation, COLUMN -> vertical, BEAM -> not vertical. Contradictions slot n / n+1 (structural
    members): BAHAMAR 194 / 0, ANUSHA 7.135 14 / 2, AMOL 7.135 6 / 1, CHOWNS 6.336 58 / 0, defaultAdapt 6.322 7 / 0;
    f64 jobs keep slot n (WLCSC 7.331 0 / 10, Greenwood 7.312 0 / 182, 50_Binney 7.243 11 / 154)."""
    def bad(shift):
        k = 0
        for n, p1, p2, sh, _ in recs:
            o = (n + shift) * slot + toff
            t = _ascii(idx[o:o + 32])
            if sh is None or t not in ("BEAM", "COLUMN", "JOIST", "VERTICAL BRACE", "HORIZONTAL BRACE"):
                continue
            d = np.subtract(p2, p1); L = float(np.linalg.norm(d))
            if not np.isfinite(L) or L < 1e-6:
                continue
            vert = abs(d[2]) / L > 0.99
            k += ((t == "JOIST") != bool(_JOIST_SEC.match(sh.name))) or (t == "COLUMN" and not vert) or (t == "BEAM" and vert)
        return k
    default = 1 if fw == 4 else 0
    b_def, b_alt = bad(default), bad(1 - default)
    return (1 - default) if (b_def >= 3 and b_alt * 2 < b_def) else default


def read_members(job, layout=None):'''),
("""        if roll != roll or abs(roll) > 7:
            roll = 0.0
        out.append(Member(n, _ascii(s[L["type"]:L["type"] + 32]), p1, p2, shapes.get(sec), roll))
    return out, L""",
"""        if roll != roll or abs(roll) > 7:
            roll = 0.0
        recs.append((n, p1, p2, shapes.get(sec), roll))
    shift = L.get("type_shift")
    if shift is None:
        with np.errstate(all="ignore"):
            shift = _type_shift(idx, L["slot"], L["type"], recs, L.get("fw", 8))
        L = dict(L, type_shift=shift)
    for n, p1, p2, sh, roll in recs:
        o = (n + shift) * L["slot"] + L["type"]
        out.append(Member(n, _ascii(idx[o:o + 32]), p1, p2, sh, roll))
    return out, L"""),
]
# the `out = []` line of read_members (only the one followed by `for n in ids:` and the slot slice)
EDITS["decode/sds2job.py"].append((
"""    out = []
    for n in ids:
        s = idx[n * L["slot"]:(n + 1) * L["slot"]]""",
"""    out = []; recs = []
    for n in ids:
        s = idx[n * L["slot"]:(n + 1) * L["slot"]]"""))

# ---------------------------------------------------------------- to_step2.py: joists and envelopes
EDITS["decode/to_step2.py"] = [
("""import to_step as T
import brep
""",
"""import to_step as T
import brep
import joist_catalog as JC
"""),
("""    mtype = {m.id: m.type for m in mems}
    mem_by_id = {m.id: m for m in mems}
    sig = {""",
"""    mtype = {m.id: m.type for m in mems}
    mem_by_id = {m.id: m for m in mems}
    joist_seats = JC.support_seats(mems)                # seat depth per joist end, measured from its supports
    job_version = read_version(job)
    sig = {"""),
# joists with attachment pieces but no joist piece (NY Bridge 7.425: 24 of 67 were dropped entirely)
("""        main_sid, inst = material_instances(job, n, pieces)
        for sid_, M_, o_ in inst:
            if sid_ == main_sid:
                frames[n] = (M_, o_); break
        if not inst:
            m = mem_by_id[n]""",
"""        main_sid, inst = material_instances(job, n, pieces)
        for sid_, M_, o_ in inst:
            if sid_ == main_sid:
                frames[n] = (M_, o_); break
        m_ = mem_by_id[n]
        if inst and JC.is_joist_member(m_) and not any(JC.is_joist_designation(pieces.get(s_, {}).get("name")) for s_, _, _ in inst):
            # joist member whose pieces are only attachments (bearing plates; NY Bridge 7.425: 24 of 67 joists were written
            # as their PL3/8 plates only): add the joist itself, derived from the designation, then the attachments below
            jp = JC.joist_part(m_, T.frame, job_version, joist_seats.get(n))
            if jp is not None:
                from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
                _k, local_j, (Mj, oj), jspec, jinfo = jp
                tj = placement(Mj, oj)
                if tj is not None:
                    label_j = JC.label(m_, n, jspec, jinfo)
                    add_flat(BRepBuilderAPI_Transform(local_j, tj, True).Shape(), label_j)
                    stats["member_fallback"] += 1
                    stats["joist_standin"] = stats.get("joist_standin", 0) + 1
                    stats["joist_standin_with_attachments"] = stats.get("joist_standin_with_attachments", 0) + 1
                    env_w[0] += jinfo["plf"] * np.linalg.norm(np.subtract(m_.p2, m_.p1)) / 12
                    add_row(dict(member=n, member_type=m_.type, piece=0, inst=0, name=m_.section.name, kind="member",
                                 builder="joist_openweb_standin", ox=round(m_.p1[0], 4), oy=round(m_.p1[1], 4),
                                 oz=round(m_.p1[2], 4)),
                            label=label_j, standin=JC.why(jspec, jinfo), real=f"open-web steel joist {m_.section.name} (vendor-designed)")
        if not inst:
            m = mem_by_id[n]"""),
# no pieces: joist from the catalog (designation decides, not the member type); v5 joist.py stays as the fallback
("""            if mtype[n] not in T.STRUCTURAL:
                n_members_without_geometry += 1
                continue
            sec = m.section.name if m.section else ""
            sh = None
            if T.is_joist(m):""",
"""            if mtype[n] not in T.STRUCTURAL and not JC.is_joist_member(m):
                n_members_without_geometry += 1
                continue
            sec = m.section.name if m.section else ""
            sh = None
            jp = JC.joist_part(m, T.frame, job_version, joist_seats.get(n)) if JC.is_joist_member(m) else None
            if jp is not None and placement(jp[2][0], jp[2][1]) is not None:
                from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
                _k, local_j, (Mj, oj), jspec, jinfo = jp
                sh = BRepBuilderAPI_Transform(local_j, placement(Mj, oj), True).Shape()
                label = JC.label(m, n, jspec, jinfo)
                builder, why = "joist_openweb_standin", JC.why(jspec, jinfo)
                real = f"open-web steel joist {sec} (vendor-designed)"
                stats["joist_standin"] = stats.get("joist_standin", 0) + 1
                env_w[0] += jinfo["plf"] * np.linalg.norm(np.subtract(m.p2, m.p1)) / 12
            elif T.is_joist(m):"""),
# envelope: joist box only for joist designations; members without any material in the job tagged as such
("""                why = "member work-line envelope: the job has no fabricated pieces for this member"
                if m.section is not None and m.section.name in T.PROFILE_NOTES:
                    why += f"; {T.PROFILE_NOTES[m.section.name]} (real section dimensions not in the job)"
                label = _tag(f"{m.type} #{n} / {sec} (member envelope)", why)
                builder, real = ("joist_envelope_approx", f"open-web steel joist {sec}") if m.type == "JOIST" else \\
                    ("member_envelope", f"{m.type} {sec}")
                if m.type == "JOIST":
                    stats["joist_envelope"] = stats.get("joist_envelope", 0) + 1""",
"""                joist = JC.is_joist_member(m)
                # placement-only member file (116 / 136 B) or no valid main piece: SDS2 never generated this member's
                # material (Revit-imported / undetailed members) - a source state, not a decode miss
                undetailed = not joist and (os.path.getsize(os.path.join(job, "mem", str(n))) <= 200 or main_sid not in pieces)
                why = ("member work-line envelope: the job has no fabricated material for this member (never detailed / "
                       "imported), nominal section on the work line" if undetailed else
                       "member work-line envelope: the job has no fabricated pieces for this member")
                if m.section is not None and m.section.name in T.PROFILE_NOTES:
                    why += f"; {T.PROFILE_NOTES[m.section.name]} (real section dimensions not in the job)"
                label = _tag(f"{m.type} #{n} / {sec} (member envelope)", why)
                builder, real = ("joist_envelope_approx", f"open-web steel joist {sec}") if joist else \\
                    ("member_undetailed_profile" if undetailed else "member_envelope", f"{m.type} {sec}")
                if joist:
                    stats["joist_envelope"] = stats.get("joist_envelope", 0) + 1"""),
]

# ---------------------------------------------------------------- to_step.py (stage 1)
EDITS["decode/to_step.py"] = [
("""    import joist as J
    rows, n_ok = [], 0
    for m in mems:
        if m.type not in STRUCTURAL:
            continue
        note = ""
        if is_joist(m):""",
"""    import joist as J
    import joist_catalog as JC
    seats = JC.support_seats(mems)
    rows, n_ok = [], 0
    for m in mems:
        if m.type not in STRUCTURAL and not JC.is_joist_member(m):
            continue
        note = ""
        jp = JC.joist_part(m, frame, read_version(job), seats.get(m.id)) if JC.is_joist_member(m) else None
        if jp is not None:
            from OCP.gp import gp_Trsf
            from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
            _k, local, (M, o), spec, info = jp
            t = gp_Trsf(); R = M.T
            t.SetValues(*R[0], o[0] * MM, *R[1], o[1] * MM, *R[2], o[2] * MM)
            sh = BRepBuilderAPI_Transform(local, t, True).Shape()
            note = JC.why(spec, info)
        elif is_joist(m):"""),
]

# ---------------------------------------------------------------- manifest.py: the new stand-in type
EDITS["decode/manifest.py"] = [
("""    "member_envelope": "fabricated pieces for the member (cut length, copes, holes); the job has only its work line and section",""",
"""    "member_envelope": "fabricated pieces for the member (cut length, copes, holes); the job has only its work line and section",
    "member_undetailed_profile": "nothing further exists in the source: SDS2 never generated material for this member (never "
                                 "detailed / imported); written as its exact nominal section on the work line","""),
("""    if b == "member_envelope": return "member_envelope\"""",
"""    if b == "member_envelope": return "member_envelope"
    if b == "member_undetailed_profile": return "member_undetailed_profile\""""),
]


def main(root):
    new = {}
    for rel, edits in EDITS.items():
        p = os.path.join(root, rel)
        s = open(p, encoding="utf-8").read()
        for old, rep in edits:
            n = s.count(old)
            if n != 1:
                raise SystemExit(f"{rel}: anchor found {n} times (expected 1):\n{old[:200]}")
            s = s.replace(old, rep, 1)
        new[p] = s
    for p, s in new.items():
        open(p, "w", encoding="utf-8").write(s)
        print("patched", p)
    if not os.path.exists(os.path.join(root, "decode", "joist_catalog.py")):
        print("NOTE: copy patch/decode/joist_catalog.py and joist_catalog.json into", os.path.join(root, "decode"))


if __name__ == "__main__":
    main(sys.argv[1])
