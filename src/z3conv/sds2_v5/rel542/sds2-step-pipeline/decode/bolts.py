"""SDS2 bolt records (mem/<n>).

Found on 7.425 TRI NORTH (682-byte records; 7.243 used 658) by searching member files for the known hole-stack
positions: each bolt is one record
  +0    3 x 3 f64 orientation R (row 3 = bolt axis)
  +72   3 x f64 head-side point p, in the member's main-material frame (world = O0 + R0.T @ p, R0 / O0 = the member
        file's matrix at 0x88 / origin at 0xD0); p is the entry face of the ply stack
  +96   f64 bolt diameter, +104 f64 bolt length, +112 f64 (pi/2 in every record seen), +120 f64 grip
  +152  u8  bolt type (index into jsetup bolts.bolt_list[])
The plies occupy z in [-grip, 0] of the record frame (points p + R.T @ (0, 0, z)).
7.0xx / early 7.1xx (SUNY, RCMS, SARALEE; 128- / 512-byte records): same matrix + position, then f32 diameter +96,
length +100, (pi/2 or 0) +104, grip +108; the type byte isn't identified there.
The position frame is the member's main material placement (on 7.2+ identical to the header block 0x88 / 0xD0).
Records are found by signature (orthonormal matrix, position, then plausible diameter / length / grip), so the
record size doesn't need to be known per version.
"""
import os, re, struct
import numpy as np

DIAS = {0.375, 0.5, 0.625, 0.75, 0.875, 1.0, 1.125, 1.25, 1.375, 1.5, 1.75, 2.0}


def bolt_types(job):
    """jsetup bolts.bolt_list[i].bolt_type -> {i: 'A325N', ...}."""
    try:
        t = open(os.path.join(job, "main", "jsetup"), "rb").read().decode("latin-1")
    except OSError:
        return {}
    return {int(m.group(1)): m.group(2).strip() for m in re.finditer(r"^bolts\.bolt_list\[(\d+)\]\.bolt_type (.+)$", t, re.M)}


def member_bolts(job, n, frame=None):
    """Bolt records of member n -> list of dict(head world point, axis world unit vector (towards the plies),
    dia, length, grip, type index or None, record offset). frame = (M, o) of the member's main material placement
    (world = o + M.T @ local); default: the member file's header block (matrix 0x88, origin 0xD0, 7.2xx+)."""
    try:
        b = open(os.path.join(job, "mem", str(n)), "rb").read()
    except OSError:
        return []
    if frame is not None:
        R0, O0 = np.asarray(frame[0], float), np.asarray(frame[1], float)
    else:
        if len(b) < 0xE8: return []
        R0 = np.array(struct.unpack(">9d", b[0x88:0xD0])).reshape(3, 3); O0 = np.array(struct.unpack(">3d", b[0xD0:0xE8]))
    with np.errstate(all="ignore"):
        if not np.isfinite(R0).all() or np.abs(R0 @ R0.T - np.eye(3)).max() > 1e-6:
            return []
    out = []
    for al in range(8):
        k = (len(b) - al) // 8
        if k < 16: continue
        d = np.frombuffer(b[al:al + 8 * k], ">f8").astype(float)
        with np.errstate(all="ignore"):
            # candidate record starts: an orthonormal f64 matrix followed by an f64 position
            Wn = np.lib.stride_tricks.sliding_window_view(d, 12)
            r1 = (Wn[:, 0:3] ** 2).sum(1); r2 = (Wn[:, 3:6] ** 2).sum(1); r3 = (Wn[:, 6:9] ** 2).sum(1)
            ok = (np.abs(r1 - 1) < 1e-6) & (np.abs(r2 - 1) < 1e-6) & (np.abs(r3 - 1) < 1e-6)
            for i in np.where(ok)[0]:
                R = d[i:i + 9].reshape(3, 3)
                if not np.isfinite(R).all() or np.abs(R @ R.T - np.eye(3)).max() > 1e-6: continue
                p = d[i + 9:i + 12]
                if not np.isfinite(p).all() or np.abs(p).max() > 1e6: continue
                q = al + 8 * int(i)
                if q + 112 > len(b): continue
                # 7.1xx-8.0xx: f64 diameter +96, length +104, grip +120, type u8 +152
                dia, L = struct.unpack(">2d", b[q + 96:q + 112])
                grip = struct.unpack(">d", b[q + 120:q + 128])[0] if q + 128 <= len(b) else -1
                typ = b[q + 152] if q + 153 <= len(b) else None; lay = "f64"
                if not (round(dia, 6) in DIAS and 0 < grip < L < 60):
                    lay = "f32"
                    # 7.0xx / early 7.1xx: f32 diameter +96, length +100, grip +108 (type not identified)
                    dia, L, _, grip = struct.unpack(">4f", b[q + 96:q + 112]); typ = None
                    if not (round(dia, 4) in DIAS and 0 < grip < L < 60 and abs(L * 8 - round(L * 8)) < 1e-4): continue
                out.append(dict(head=O0 + R0.T @ p, axis=-(R0.T @ R[2]), dia=float(dia), length=float(L), grip=float(grip),
                                type=typ, layout=lay, offset=q, member=n))
    out.sort(key=lambda r: r["offset"])
    # drop overlapping duplicates (the same record seen through a shifted window)
    keep, last = [], -10 ** 9
    for r in out:
        if r["offset"] - last >= 128: keep.append(r); last = r["offset"]
    return keep


def job_bolts(job, members=None, frames=None):
    """All bolt records of the job; frames {member: (M, o)} of each member's main material (else header frame)."""
    names = members if members is not None else sorted(int(f) for f in os.listdir(os.path.join(job, "mem")) if f.isdigit())
    out = []
    for n in names:
        out += member_bolts(job, n, (frames or {}).get(n))
    return out


def main_frames(job, pieces):
    """{member: (M, o)} of each member's main material placement (all layouts)."""
    from instances import material_instances
    from sds2job import read_members
    mems, _ = read_members(job); fr = {}
    for m in mems:
        try:
            main, inst = material_instances(job, m.id, pieces)
        except Exception:
            continue
        for sid, M, o in inst:
            if sid == main:
                fr[m.id] = (M, o); break
    return fr
