"""Material instances and bolt/hole groups of each member (7.243 layout, 50_Binney).

mem/<n> = 662-byte header, then
  material blocks, 538 B each (interleaved with hole groups; header block at 0x7C = main material):
      +0x0C  3x3 f64 BE rotation (row-major)
      +0x54  3 x f64 origin, GLOBAL job coords (inches)
      +0x6C  i32 subm id (piece geometry in subm/<id>, local coords)
      +0x70  i32 member id, or 0 (e.g. MISC members)
  bolt/hole blocks, 658 B each, relative to R = subm-id offset:
      R-334  3x3 rotation, R-262 position (member-local), R-238 f64 hole dia, ...; R+8 member id
Main material: mem/<n> +0xE8 i32 subm id.
"""
import os, re, struct
import numpy as np

MAT0, MATLEN = 0x296, 538


def _scan_vertices(b, tags, id_filter):
    """Vertex records: tag byte, u24 id, 3 x f64 BE, in file order (end-face outlines come first, in boundary order).
    Records are variable length (fillet/arc vertices carry extra data), so scan byte by byte. With id_filter, only
    odd ids are kept: vertex ids are always odd (0x41, 0x851, 0x076911, ...), while the hole/dimension records after
    the vertex table carry even ids (0, 0x4000, 0x6000, 0xC000) and coordinates that are not piece geometry
    (7.425: rolled pieces 78% -> 98% matching their piece-table size)."""
    out = {t: [] for t in tags}
    o = 0x20
    with np.errstate(all="ignore"):
        while o + 28 <= len(b):
            t = b[o]
            if t in out:
                vid = int.from_bytes(b[o + 1:o + 4], "big")
                if (vid & 1) if id_filter else b[o + 1] == 0:
                    v = struct.unpack(">3d", b[o + 4:o + 28])
                    if all(np.isfinite(v)) and all(abs(x) < 1e4 for x in v) and all(x == 0 or abs(x) > 1e-6 for x in v):
                        out[t].append(v); o += 28; continue
            o += 1
    return max(out.values(), key=len)


def subm_vertices(job, sid, cache={}):
    """Vertex coordinates of piece subm/<id> (piece-local, inches). The tag byte differs between piece files
    (1 rolled, 2 plates, 3 round HSS, 11 bent plates, ...); the richest tag wins."""
    key = (job, sid)
    if key in cache: return cache[key]
    p = os.path.join(job, "subm", str(sid))
    if not os.path.exists(p): cache[key] = None; return None
    b = open(p, "rb").read()
    if _is_71(job):
        # 7.1xx: u32 vertex count at 0x0E, then that many packed 3 x f64 (no per-record tag) from 0x1E;
        # 7.0xx: the same with the header 8 bytes shorter (count 0x06, vertices from 0x16)
        hc, hv = (0x06, 0x16) if _is_70(job) else (0x0E, 0x1E)
        nv = struct.unpack(">I", b[hc:hc + 4])[0] if len(b) >= hv else 0
        if 0 < nv and hv + 24 * nv <= len(b):
            V = np.array(struct.unpack(">%dd" % (3 * nv), b[hv:hv + 24 * nv])).reshape(nv, 3)
            if np.isfinite(V).all() and np.abs(V).max() < 1e5:
                cache[key] = V
                return V
    best = _scan_vertices(b, tuple(range(1, 16)), True)
    if len(best) < 4:                         # older layouts: original unfiltered scan
        best = _scan_vertices(b, (1, 2), False)
    cache[key] = np.array(best) if best else None
    return cache[key]


def _is_frame(M):
    """Orthonormal 3x3 rotation (det +-1). NaN-safe: a coincidental piece-id match can sit next to doubles that
    overflow (1e226 x 1e267 -> inf - inf = NaN), and `NaN > tol` is False, so the v4 test let such blocks through
    (Greenwood 7.312: 29 phantom placements at the origin, all reported as skipped pieces)."""
    with np.errstate(all="ignore"):
        if not np.isfinite(M).all() or np.abs(M).max() > 1.0 + 1e-6:
            return False
        e = np.abs(M @ M.T - np.eye(3)).max()
        d = abs(abs(np.linalg.det(M)) - 1)
    return bool(e <= 1e-3 and d <= 1e-3)


def piece_vertices(job, sid, cache={}):
    """Vertices of piece subm/<id> that its own faces reference (brep.parse), in file order; falls back to the tagged
    vertex scan (subm_vertices) when the file has no readable topology. The vertex table also holds records no face
    uses: HSS reference squares (an HSS12x2 file carries points 12 in apart across its 2-in side), work points and
    hole/dimension markers. The approximate builders fitted their profile to those too (FIX items 11 / 13)."""
    key = (job, sid)
    if key in cache:
        return cache[key]
    V = None
    p = os.path.join(job, "subm", str(sid))
    if os.path.exists(p):
        try:
            import brep
            r = brep.parse(open(p, "rb").read())
            if r is not None:
                used = sorted({i for f in r[1] for i in f})
                if len(used) >= 4:
                    V = np.asarray(r[0])[used]
        except Exception:
            V = None
    if V is None:
        V = subm_vertices(job, sid)
    cache[key] = V
    return V


def _is_71(job, cache={}):
    """7.1xx member files: same block geometry (rotation B+0x0C, origin B+0x54, f64) but the piece id is a u16 at
    B+0x6C (512-B blocks, main block at B=0x68, main piece u16 at 0xD4) and the next word is not the member id, so
    only the orthonormal-rotation / finite-origin checks decide. Chosen from the job's subm_idx layout (440-B)."""
    if job not in cache:
        from piece_table import slot_size
        cache[job] = slot_size(open(os.path.join(job, "subm", "subm_idx"), "rb").read(64 * 1024)) in (440, 384)  # 7.1 / 7.0
    return cache[job]


def _is_70(job, cache={}):
    if job not in cache:
        from piece_table import slot_size
        cache[job] = slot_size(open(os.path.join(job, "subm", "subm_idx"), "rb").read(64 * 1024)) == 384
    return cache[job]


def _member_ids(job, cache={}):
    if job not in cache:
        cache[job] = np.array(sorted(int(x) for x in os.listdir(os.path.join(job, "mem")) if x.isdigit()), dtype=np.int64)
    return cache[job]


def _instances_71(b, keys, v70=False):
    out = []
    if len(b) < 0x6A:
        return 0, out
    v = np.frombuffer(b[:len(b) // 2 * 2], dtype=">u2").astype(np.int64)
    for i in np.where(np.isin(v, keys))[0]:
        X = 2 * int(i); B = X - 0x6C
        if B + 0x0C < 0: continue                  # 7.0xx: the main block starts 4 bytes before the file (B = -4)
        with np.errstate(all="ignore"):
            M = np.array(struct.unpack(">9d", b[B + 0x0C:B + 0x54])).reshape(3, 3)
            o = np.array(struct.unpack(">3d", b[B + 0x54:B + 0x6C]))
            if not (np.isfinite(M).all() and np.isfinite(o).all()) or np.abs(o).max() > 1e6: continue
            if not _is_frame(M): continue
        out.append((int(v[i]), M, o))
    mo = 0x68 if v70 else 0xD4                     # main piece: 7.0xx u16 at 0x68, 7.1xx at 0xD4
    main = struct.unpack(">H", b[mo:mo + 2])[0] if len(b) >= mo + 2 else 0
    return main, out


def material_instances(job, n, pieces):
    """All 538-B-style material blocks in mem/<n>: piece id at X (= B+0x6C), X+4 == n or 0, rotation at B+0x0C,
    global origin at B+0x54. Includes the header block at B=0x7C (main material: matrix 0x88, origin 0xD0, piece 0xE8).
    Blocks are interleaved with bolt/hole groups, so every even offset is checked (vectorised).
    7.1xx: u16 piece id at B+0x6C, no member-id check (see _is_71)."""
    b = open(os.path.join(job, "mem", str(n)), "rb").read()
    keys = np.fromiter(pieces.keys(), dtype=np.int64) if not hasattr(material_instances, "_k") or material_instances._kid != id(pieces) else material_instances._k
    material_instances._k, material_instances._kid = keys, id(pieces)
    if _is_71(job):
        return _instances_71(b, keys, _is_70(job))
    out, seen = [], set()
    for al in (0, 2):
        m4 = (len(b) - al) // 4
        if m4 < 2: continue
        v = np.frombuffer(b[al:al + 4 * m4], dtype=">i4").astype(np.int64)
        # owner word after the piece id: this member, 0, or another member's id (connection material attached to
        # this member but owned by the connecting one - listed only here; TRI NORTH: 1,144 such placements, 3.2 t)
        cand = np.where(np.isin(v[:-1], keys) & ((v[1:] == n) | (v[1:] == 0) | np.isin(v[1:], _member_ids(job))))[0]
        for i in cand:
            X = al + 4 * int(i)
            B = X - 0x6C
            if B < 0 or X in seen: continue
            with np.errstate(all="ignore"):
                M = np.array(struct.unpack(">9d", b[B + 0x0C:B + 0x54])).reshape(3, 3)
                o = np.array(struct.unpack(">3d", b[B + 0x54:B + 0x6C]))
                if not (np.isfinite(M).all() and np.isfinite(o).all()) or np.abs(o).max() > 1e6: continue
                if not _is_frame(M): continue
            seen.add(X)
            out.append((int(v[i]), M, o))
    main = struct.unpack(">i", b[0xE8:0xEC])[0] if len(b) >= 0xEC else 0
    return main, out

def hole_groups(job, n):
    b = open(os.path.join(job, "mem", str(n)), "rb").read()
    tag = struct.pack(">i", n)
    out = []
    for m in re.finditer(re.escape(tag), b):
        R = m.start() - 8
        if R < 334 or R + 24 > len(b) or R < MAT0: continue
        M = np.array(struct.unpack(">9d", b[R - 334:R - 262])).reshape(3, 3)
        pos = np.array(struct.unpack(">3d", b[R - 262:R - 238]))
        with np.errstate(all="ignore"):
            if not (np.isfinite(M).all() and np.isfinite(pos).all()) or abs(abs(np.linalg.det(M)) - 1) > 1e-3: continue
        dia = struct.unpack(">d", b[R - 238:R - 230])[0]
        out.append((struct.unpack(">i", b[R:R + 4])[0], M, pos, dia))
    return out




