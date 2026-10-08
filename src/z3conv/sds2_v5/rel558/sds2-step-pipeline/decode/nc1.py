"""Opt-in: holes from the job's own NC1 / DSTV files for main W-shape members (v5.5.4, `--nc1 <dir|zip>`).

SDS2 7.2/7.3 piece files keep most main-member holes, but not all: on 12 data-3 jobs, 91 % of the holes in
strictly matched NC1 files are already in the decoded B-rep, and 969 round holes sit on a face whose other holes do
match yet have no decoded hole within 25 mm. Only those are cut, and only when everything is unambiguous:

  match   the NC1 header order line equals the job folder name, the NC1 piece mark equals the member's decoded mark
          (mem_idx slot: i16 at the section field + 4 -> pcm/pcm_list record), every member with that mark has the
          same main piece, the piece length is within 3 mm, the profile name is equal, and the code is I with a W
          profile. NC1 files for one mark that disagree (revisions) -> no cut.
  frame   DSTV x runs from the piece's local x minimum; web faces (v / h) measure y from the local y minimum, flange
          faces (o / u) from the local z minimum. Fitted on Cats Rail 7.312: 193 / 195 faces fully matched to decoded
          holes. A face is cut only when at least one of its NC1 holes matches a decoded hole there; that hole is the
          template for entry point, axis and depth (which flange, which web side).
  hole    position and diameter exactly as stored in the NC1 file; round holes only (slots are skipped); never where a
          decoded hole lies within 25 mm. Tagged holes_from_nc1.
"""
import os, re, io, zipfile, collections, struct
import numpy as np

BLOCK = re.compile(r"^(ST|EN|BO|SI|AK|IK|PU|KO|SC|TO|UE|PR|KA|EB|VB|LP|RT|WA|FP|LB|RO|SN)\s*$")
NUM = re.compile(r"^(-?\d+(?:\.\d+)?)([a-z]*)$")
MM = 25.4


def parse_nc1(text):
    """DSTV NC1 -> dict(order, mark, profile, code, length, holes=[dict(face, x, y, d, slot)]) (mm)."""
    L = text.replace("\r", "").split("\n")
    i = 0
    while i < len(L) and L[i].strip() != "ST":
        i += 1
    hdr = []; i += 1
    while i < len(L) and not (BLOCK.match(L[i].strip()) and len(hdr) >= 9):
        s = L[i].strip()
        if not s.startswith("**"):
            hdr.append(s)
        i += 1

    def h(k, conv=str):
        try:
            return conv(hdr[k])
        except (IndexError, ValueError):
            return None
    part = dict(order=h(0), mark=h(3), profile=h(6) or "", code=h(7) or "", length=h(8, float), holes=[])
    cur = None
    for line in L[i:]:
        m = BLOCK.match(line.strip())
        if m:
            cur = m.group(1); continue
        if cur != "BO" or not line.strip():
            continue
        tok = line.split()
        face = tok[0] if tok and tok[0].isalpha() else "v"
        vals = tok[1:] if tok and tok[0].isalpha() else tok
        nums = []
        for t in vals:
            mm = NUM.match(t)
            if mm:
                nums.append((float(mm.group(1)), mm.group(2)))
        if len(nums) < 3:
            continue
        slot = len(nums) >= 7 or (len(nums) > 3 and "l" in nums[3][1])
        part["holes"].append(dict(face=face, x=nums[0][0], y=nums[1][0], d=nums[2][0], slot=slot))
    return part


def read_source(src):
    """dir (recursive) or zip of .nc1 files -> list of parsed parts."""
    out = []
    if os.path.isdir(src):
        for root, _, files in os.walk(src):
            for f in sorted(files):
                if f.lower().endswith(".nc1"):
                    with open(os.path.join(root, f), "rb") as fh:
                        out.append(parse_nc1(fh.read().decode("latin-1")))
    elif zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as z:
            for n in sorted(z.namelist()):
                if n.lower().endswith(".nc1"):
                    out.append(parse_nc1(z.read(n).decode("latin-1")))
    return out


_norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
_prof = lambda s: re.sub(r"[^A-Z0-9/.]", "", (s or "").upper())


def member_marks(job, mems, layout):
    """member id -> decoded piece mark (pcm/pcm_list, 72-B records from 256; index = i16 at the section field + 4)."""
    try:
        b = open(os.path.join(job, "pcm", "pcm_list"), "rb").read()
        idx = open(os.path.join(job, "mem", "mem_idx"), "rb").read()
    except OSError:
        return {}
    n = (len(b) - 256) // 72
    marks = [b[256 + 72 * k: 256 + 72 * k + 40].split(b"\x00")[0].decode("latin-1").strip() for k in range(max(n, 0))]
    S, so = layout["slot"], layout["sec"] + 4
    out = {}
    for m in mems:
        s = idx[m.id * S + so: m.id * S + so + 2]
        if len(s) == 2:
            v = struct.unpack(">h", s)[0]
            if 0 < v < n and marks[v]:
                out[m.id] = marks[v]
    return out


def plan(job, src, mems, layout, pieces):
    """-> ({piece id: NC1 part}, stats). Strict match only (module docstring)."""
    st = collections.Counter()
    parts = read_source(src)
    st["nc1 parts"] = len(parts)
    base = os.path.basename(os.path.normpath(job))
    # the job folder is SDS2's job name; batch copies may carry a "_<6 hex>" id suffix (1544_-_Cats_Rail_..._6e9e32);
    # SDS2_JOB_NAME overrides when the folder was renamed
    names = {_norm(os.environ.get("SDS2_JOB_NAME", "")), _norm(base), _norm(re.sub(r"_[0-9a-f]{6}$", "", base))} - {""}
    mk = member_marks(job, mems, layout)
    main = {}
    for mid in mk:
        try:
            with open(os.path.join(job, "mem", str(mid)), "rb") as f:
                h = f.read(0xEC)
            main[mid] = struct.unpack(">i", h[0xE8:0xEC])[0] if len(h) >= 0xEC else None
        except OSError:
            main[mid] = None
    by_mark = collections.defaultdict(set)
    for mid, m_ in mk.items():
        by_mark[m_].add(main.get(mid))
    nc = collections.defaultdict(list)
    for p in parts:
        if p["holes"] and p["code"] == "I" and _prof(p["profile"]).startswith("W"):
            nc[p["mark"]].append(p)
    out = {}
    for mark, ps in nc.items():
        st["W parts with holes"] += 1
        sig = {(round(p["length"] or 0, 1), tuple((h["face"], h["x"], h["y"], h["d"]) for h in p["holes"])) for p in ps}
        if len(sig) > 1:
            st["skipped: NC1 revisions disagree"] += 1; continue
        p = ps[0]
        if _norm(p["order"]) not in names:
            st["skipped: order is not this job"] += 1; continue
        sids = by_mark.get(mark)
        if not sids:
            st["skipped: mark not on a member"] += 1; continue
        if len(sids) != 1 or None in sids:
            st["skipped: mark on members with different main pieces"] += 1; continue
        sid = next(iter(sids)); pc = pieces.get(sid)
        if pc is None or p["length"] is None or abs(pc["L"] * MM - p["length"]) > 3.0:
            st["skipped: length differs > 3 mm"] += 1; continue
        if _prof(pc["name"]) != _prof(p["profile"]):
            st["skipped: profile differs"] += 1; continue
        if sid in out:
            st["skipped: two marks on one piece"] += 1; out.pop(sid); continue
        out[sid] = p; st["matched W parts"] += 1
    return out, st


def extra_holes(part, V, faces, H, tol=1.5, gap=25.0):
    """NC1 holes of one matched piece that SDS2's piece file lacks, as piece-local hole dicts for brep.cut_holes.
    Only on faces where another NC1 hole matches a decoded hole (the template); round holes only."""
    used = sorted({i for f in faces for i in f})
    if not used or not H:
        return [], collections.Counter()
    lo = V[used].min(0) * MM
    st = collections.Counter()
    D = [(np.asarray(h["c"], float) * MM, h) for h in H]
    out = []
    for face in sorted({h["face"] for h in part["holes"]}):
        ax = 1 if face in ("v", "h") else 2 if face in ("o", "u") else None
        Hn = [h for h in part["holes"] if h["face"] == face]
        if ax is None:
            st["face not v/h/o/u"] += len(Hn); continue
        pos = lambda h: (lo[0] + h["x"], lo[ax] + h["y"])
        tmpl = None; matched = set(); used_d = set()
        for k, h in enumerate(Hn):
            x, y = pos(h)
            for j, (c, hd) in enumerate(D):
                if abs(c[0] - x) < tol and abs(c[ax] - y) < tol and abs(hd["dia"] * MM - h["d"]) < 1.0:
                    matched.add(k); used_d.add(j); tmpl = tmpl or hd; break
        if tmpl is None:
            st["face without a matching decoded hole (not cut)"] += len(Hn); continue
        # every decoded hole on this face (same axis, same plane as the template) must be one of the NC1 holes;
        # otherwise the two disagree on positions (mirrored / revised piece) and nothing is cut there
        a_t = np.asarray(tmpl["axis"], float); k_ = 3 - ax                 # the coordinate along the hole axis
        c_t = np.asarray(tmpl["c"], float) * MM
        on_face = [j for j, (c, hd) in enumerate(D)
                   if abs(abs(np.asarray(hd["axis"], float) @ a_t) - 1) < 0.01 and abs(c[k_] - c_t[k_]) < 0.5 * MM]
        if any(j not in used_d for j in on_face):
            st["face where decoded and NC1 holes disagree (not cut)"] += len(Hn) - len(matched); continue
        for k, h in enumerate(Hn):
            if k in matched:
                continue
            if h["slot"] or h["d"] <= 0:
                st["slot / mark (not cut)"] += 1; continue
            x, y = pos(h)
            if any(np.hypot(c[0] - x, c[ax] - y) < gap for c, _ in D):
                st["decoded hole within 25 mm (not cut)"] += 1; continue
            c = np.asarray(tmpl["c"], float).copy(); c[0] = x / MM; c[ax] = y / MM
            out.append(dict(c=c, axis=np.asarray(tmpl["axis"], float), depth=tmpl["depth"], dia=h["d"] / MM, bolt=0.0,
                            slot=0.0, ang=0.0, R=np.eye(3), type=0))
            st["cut"] += 1
    return out, st
