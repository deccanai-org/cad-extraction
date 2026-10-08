"""Reader for SDS2 7.x job folders (no SDS2 needed).

mem/mem_idx holds one fixed-size slot per member n at n*slot. Layout is auto-calibrated per job:
                    7.243 (50_Binney)   7.312 (Greenwood)   7.425 (Sheriff)
  slot size         2494                2944                2976
  +type ASCII       0x988               0xA78               0xA98
  +left  pt 3xf64   0x112               0x112               0x112
  +right pt 3xf64   0x172               0x186               0x186
  +section i16      0x1D4               0x1FC               ?
  +roll f64         section+6
Validated on 50_Binney against the job's own IFC (94% of beams/columns matched, 83-86% within 0.25in).

main/job_mtrl (7.2-7.3): 510-byte records from 0x2FE; name ASCII at +0; f64 BE at +0x1A d, +0x22 bf, +0x2A tf,
    +0x32 tw, +0x3A k, +0x42 weight (lb/ft). Section field value = record index + 1.
main/jsetup: text, first line "version 7.xxx".
"""
import os, re, struct, collections
from dataclasses import dataclass
import numpy as np

MTRL_BASE, MTRL_REC = 0x2FE, 510
ALLOW_71 = True           # 7.1xx layout (f32 mem_idx, 440-B subm_idx): validated on 7 jobs + a converted twin
SHAPE_FAMILIES = {"W", "M", "S", "HP", "HSS", "TS", "C", "MC", "L", "WT", "MT", "ST", "PIPE", "PLG", "WBX", "WPS"}


@dataclass
class Shape:
    index: int
    name: str
    d: float
    bf: float
    tf: float
    tw: float
    k: float
    weight: float
    bf_top: float = None
    tf_top: float = None
    bf_bot: float = None
    tf_bot: float = None

    @property
    def family(self):
        m = re.match(r"[A-Z]+", self.name)
        return m.group() if m else ""


@dataclass
class Member:
    id: int
    type: str
    p1: tuple
    p2: tuple
    section: "Shape | None"
    roll: float


def _ascii(b):
    m = re.match(rb"[ -~]+", b)
    return m.group().decode() if m else ""


def read_version(job):
    try:
        with open(os.path.join(job, "main", "jsetup"), "rb") as f:
            m = re.match(rb"\s*version\s+([0-9.]+)", f.read(64))
            return m.group(1).decode() if m else ""
    except OSError:
        return ""


def _read_shapes_archive(b):
    """7.4xx job_mtrl: boost::serialization archive, little-endian, variable-length records.
    Section record: u32 23, name[23] NUL-padded, u8 type code (6 W/M/HP, 5 HSS rect, 3 HSS round/PIPE, 2 L, 1 C/MC,
    4 WT/MT, 7 joist, ...), 4 bytes, then f64 LE d, bf, tf, tw, k, weight. Section field value = record order + 1
    (validated on TRI NORTH 7.425 against every rolled piece name in subm_idx: 135/135)."""
    out = {}
    for m in re.finditer(rb"\x17\x00\x00\x00[!-~]", b):
        p = m.start()
        raw = b[p + 4:p + 27]
        name = raw.split(b"\x00")[0]
        if any(raw[len(name):]) or not re.fullmatch(rb"[ -~]+", name):
            continue
        if b[p + 27] in (0x00, 0x17):
            # not a section record: joists embed their chord angles as nested strings (followed by another string's
            # length prefix 0x17, or by 0); counting them shifted every later index (8.007 Morgan State 30K11 -> L2x2)
            continue
        d, bf, tf, tw, kk, wt = struct.unpack("<6d", b[p + 32:p + 80])
        k = len(out) + 1
        section = name.decode()
        family = re.match(r"[A-Z]+", section)
        if family and family.group() in {"PLG", "WPS", "WBX"} and p + 128 <= len(b):
            # 7.4xx stores the four fabricated flange dimensions after the
            # ordinary rolled-shape fields. The ordinary bf is a placeholder
            # (WBX24x143 records bf=1 although both flanges are 10 in wide).
            bt, tt, bb, tb = struct.unpack("<4d", b[p + 96:p + 128])
            if all(np.isfinite(v) and v > 0 for v in (bt, tt, bb, tb)):
                out[k] = Shape(k, section, d, max(bt, bb), max(tt, tb), tw, kk, wt, bt, tt, bb, tb)
                continue
        out[k] = Shape(k, section, d, bf, tf, tw, kk, wt)
    return out


def _read_shapes_fixed(b):
    """Fixed-size big-endian records of any size (7.1xx: 178 B with f32 dims): record size = most common spacing of
    section names, float width chosen so W-shape depths come out plausible. Dims at +0x1A like 7.2xx."""
    pos = [m.start() for m in re.finditer(rb"(?<![ -~])(W\d+x[\d.]+|HSS[\dx/.]+|L\d+x[\dx/.]+|C\d+x[\d.]+)\x00", b)]
    if len(pos) < 10:
        return None
    rec = collections.Counter(pos[i + 1] - pos[i] for i in range(len(pos) - 1)).most_common(1)[0][0]
    base = collections.Counter(p % rec for p in pos).most_common(1)[0][0]
    for fmt, sz in ((">6d", 48), (">6f", 24)):
        if rec < 0x1A + sz: continue
        vals = [struct.unpack(fmt, b[p + 0x1A:p + 0x1A + sz])[0] for p in pos if b[p:p + 1] == b"W"][:200]
        if vals and np.mean([0.5 < v < 60 for v in vals]) > 0.9:
            # numbering starts at the first named record (7.1xx has blank header records before it); same order
            # and index as the 7.2/7.3 table of a converted copy (Merriam 7.135 vs its 7.3-layout twin)
            first = next(k for k in range((len(b) - base) // rec) if re.match(rb"[!-~]", b[base + k * rec:base + k * rec + 1]))
            out = {}
            for k in range(first, (len(b) - base) // rec):
                r = b[base + k * rec: base + (k + 1) * rec]
                d, bf, tf, tw, kk, wt = struct.unpack(fmt, r[0x1A:0x1A + sz])
                n = k - first + 1
                out[n] = Shape(n, _ascii(r[:40]), d, bf, tf, tw, kk, wt)
            return out
    return None


def read_shapes(job):
    b = open(os.path.join(job, "main", "job_mtrl"), "rb").read()
    if b"serialization::archive" in b[:0x200]:
        return _read_shapes_archive(b)
    if (len(b) - MTRL_BASE) % MTRL_REC:
        out = _read_shapes_fixed(b)
        if out:
            return out
        raise ValueError(f"unsupported job_mtrl layout ({len(b)} bytes) - version {read_version(job)}")
    out = {}
    for k in range((len(b) - MTRL_BASE) // MTRL_REC):
        r = b[MTRL_BASE + k * MTRL_REC: MTRL_BASE + (k + 1) * MTRL_REC]
        d, bf, tf, tw, kk, wt = struct.unpack(">6d", r[0x1A:0x4A])
        name = _ascii(r[:40])
        family = re.match(r"[A-Z]+", name)
        if family and family.group() in {"PLG", "WPS", "WBX"}:
            bf_top, tf_top, bf_bot, tf_bot = struct.unpack(">4d", r[0x5A:0x7A])
            out[k + 1] = Shape(k + 1, name, d, max(bf_top, bf_bot), max(tf_top, tf_bot), tw, kk, wt,
                               bf_top, tf_top, bf_bot, tf_bot)
        else:
            out[k + 1] = Shape(k + 1, name, d, bf, tf, tw, kk, wt)
    return out


def _main_piece_agreement(job, idx, slot, toff, ids, shapes, offsets, limit=1500):
    """Share of beams/columns/braces whose i16 at each candidate offset names the same section as the member's own
    main piece (i32 at mem/<n>+0xE8, name from subm_idx). {} if the piece table can't be read."""
    try:
        from piece_table import read_pieces
        P = read_pieces(job)
    except Exception:
        return {}
    names = {}
    for n in ids:
        t = _ascii(idx[n * slot + toff:n * slot + toff + 20])
        if t not in ("BEAM", "COLUMN", "VERTICAL BRACE", "HORIZONTAL BRACE"): continue
        try:
            with open(os.path.join(job, "mem", str(n)), "rb") as f:
                h = f.read(0xEC)
        except OSError:
            continue
        if len(h) < 0xEC: continue
        v = struct.unpack(">i", h[0xE8:0xEC])[0]
        if v in P and re.match(r"(W|S|M|HP|C|MC|WT|MT|ST|HSS|TS|L|PIPE)\d", P[v]["name"]):
            names[n] = P[v]["name"]
        if len(names) >= limit: break
    if len(names) < 10:
        return {}
    out = {}
    for so in offsets:
        hit = sum(1 for n, nm in names.items()
                  if (s := shapes.get(struct.unpack(">h", idx[n * slot + so:n * slot + so + 2])[0])) and s.name == nm)
        out[so] = hit / len(names)
    return out


def calibrate(job, shapes):
    md = os.path.join(job, "mem")
    idx = open(os.path.join(md, "mem_idx"), "rb").read()
    pos = [m.start() for m in re.finditer(rb"(?<![ -~])(BEAM|COLUMN|VERTICAL BRACE|MISC|Ref Point)\x00", idx)]
    if len(pos) < 3:
        raise ValueError(f"mem_idx: too few members to calibrate ({len(pos)})")
    slot =collections.Counter(pos[i + 1] - pos[i] for i in range(len(pos) - 1)).most_common(1)[0][0]
    toff = collections.Counter(p % slot for p in pos).most_common(1)[0][0]
    ids = sorted(int(n) for n in os.listdir(md) if n.isdigit())
    if len(pos) < 3 or not ids:
        raise ValueError("mem_idx: too few members to calibrate")
    # work point: mem/<n> +0x48 holds the left end as 3 x f64; mem_idx stores it as f64 (7.2+) or f32 (7.1xx)
    for fw in ((8, 4) if slot != 1280 else ()):
        # 7.0xx (1280-B slots) never key-matches its work point; skipping it also avoids coincidental matches
        # sending calibration to a wrong offset (7.039 SCHUCKERS_JOB)
        p1c = collections.Counter()
        for n in ids[:400]:
            with open(os.path.join(md, str(n)), "rb") as f:
                k = f.read(0x60)[0x48:0x60]
            if len(k) == 24 and any(k):
                if fw == 4:
                    k = struct.pack(">3f", *struct.unpack(">3d", k))
                j = idx[n * slot:(n + 1) * slot].find(k)
                if j >= 0: p1c[j] += 1
        if p1c:
            break
    if slot == 1280:
        p1c = collections.Counter()
    if not p1c:
        # 7.0xx: the member file's reference point (+0x50) is not the work point, so no key match; the f32 end
        # points sit where 7.1xx has them (+266 / +316 in 1280-B slots). The p2 search below validates this.
        if slot == 1280:
            fw, p1c = 4, collections.Counter({266: 1})
        else:
            raise ValueError("mem_idx: member work points not found")
    p1 = p1c.most_common(1)[0][0]
    dt, pl = (">f8", 24) if fw == 8 else (">f4", 12)
    p2c = collections.Counter()
    with np.errstate(all="ignore"):
        for n in ids[:1500]:
            s = idx[n * slot:(n + 1) * slot]
            if len(s) < slot: continue
            a = np.frombuffer(s[p1:p1 + pl], dtype=dt).astype(float)
            for off in range(p1 + pl, min(slot - pl, p1 + 400), 2):
                q = np.frombuffer(s[off:off + pl], dtype=dt).astype(float)
                if not np.isfinite(q).all() or np.abs(q).max() > 1e6: continue
                dd = q - a; L = np.linalg.norm(dd)
                if 12 < L < 5000 and np.sum(np.abs(dd) < 1e-3) >= 2:
                    p2c[off] += 1
    if not p2c:
        raise ValueError("mem_idx: member end points not found")
    p2 = p2c.most_common(1)[0][0]
    # section field: i16 whose values map beams to real shape families with many distinct values
    beams = [n for n in ids if _ascii(idx[n * slot + toff:n * slot + toff + 20]) == "BEAM"][:3000]
    best = None; cands = []
    if fw == 4:
        # 7.1xx: i16 at p2+50. Validated: 699/699 members equal to the converted 7.3-layout twin (Merriam), and
        # 88-100% equal to the member's own main-piece name (mem/<n>+0xD2 -> subm_idx) on 7 jobs. The search below
        # picks p2+52 on these jobs (an adjacent field that also maps beams to W shapes), so it is not used.
        best = (0, p2 + 50)
    for so in (range(p2 + 0x30, p2 + 0xA0, 2) if fw == 8 else ()):
        vals = [struct.unpack(">h", idx[n * slot + so:n * slot + so + 2])[0] for n in beams]
        ok = [v for v in vals if v in shapes and shapes[v].family in SHAPE_FAMILIES]
        if not vals: continue
        score = len(ok) / len(vals) * min(len(set(ok)), 20)
        if best is None or score > best[0]:
            best = (score, so)
        cands.append((score, so))
    if fw == 8 and cands:
        # Neighbouring fields can also map beams to W shapes (7.613 Building_101j / Kincora: p2+0x7A beat the real
        # p2+0x76). Where the piece table is readable, pick the offset whose section equals the member's own main
        # piece name (mem/<n>+0xE8 -> subm_idx) most often; keep the heuristic only if no candidate agrees.
        agree = _main_piece_agreement(job, idx, slot, toff, ids, shapes, [so for sc, so in sorted(cands, reverse=True)[:6]])
        if agree and max(agree.values()) >= 0.5:
            best = (0, max(agree, key=agree.get))
    if best is None:
        raise ValueError("mem_idx: section field not found")
    if fw == 4 and not ALLOW_71:
        # 7.1xx: points, the section field (i16 at p2+50) and roll (f32 at sec+4); pieces in piece_table.LAYOUTS[440]
        # and instances._is_71. Set ALLOW_71 = False to refuse these jobs again.
        raise ValueError("7.1xx mem_idx layout (f32 points) - disabled (sds2job.ALLOW_71)")
    # roll: f64 at section+6 in 7.2+; f32 radians at section+4 in 7.1xx (Merriam twin: 699/699 equal, 108 non-zero)
    return dict(slot=slot, type=toff, p1=p1, p2=p2, sec=best[1], roll=best[1] + (6 if fw == 8 else 4), fw=fw)


def sparse_layout(job, shapes):
    """Validated family layout for jobs too small or homogeneous to auto-calibrate.

    ``calibrate`` deliberately needs several type markers and normally several beams.  That is a good guard for an
    unknown layout, but it rejects real seed/anchor/stair/wall jobs and all-column jobs even though the surrounding
    file family is unambiguous.  Infer the family from the fixed ``mem_idx`` slot size, then use only offsets already
    validated by this decoder.  Return None rather than guessing when the slot family or type offset is ambiguous.
    """
    md = os.path.join(job, "mem")
    idx = open(os.path.join(md, "mem_idx"), "rb").read()
    ids = sorted(int(n) for n in os.listdir(md) if n.isdigit())
    if not ids:
        return None

    # All supported families keep a 256-byte base followed by fixed slots.  8.0xx's documented 7,456-byte header is
    # 256 bytes plus two 3,600-byte reserved slots, so the same test remains valid.  Requiring enough slots for the
    # highest materialised member prevents coincidental divisibility from selecting a family.
    slots = [s for s in (1280, 1416, 2494, 2944, 2976, 3204, 3404, 3600)
             if len(idx) >= 256 and (len(idx) - 256) % s == 0 and (len(idx) - 256) // s > max(ids)]
    # v5: several slot sizes can divide the file (7.323 Tarrier: 1280 and 2944 both fit a 450-slot mem_idx); v4
    # returned None then. Validate every candidate and keep the one that types the most members.
    ver = read_version(job)
    best = []
    for slot in slots:
        r = _sparse_try(job, idx, ids, shapes, slot, ver)
        if r is not None:
            best.append(r)
    if not best:
        return None
    # tie-break on the slot family of the job's own version (7.0 1280, 7.1 1416, 7.2 2494, 7.3 2944, 7.4 2976, 7.5+)
    fam = {"7.0": (1280,), "7.1": (1416,), "7.2": (2494,), "7.3": (2944,), "7.4": (2976,)}.get(ver[:3], (3204, 3404, 3600))
    best.sort(key=lambda r: (-r[1], r[0]["slot"] not in fam))
    if len(best) > 1 and best[0][1] == best[1][1] and (best[0][0]["slot"] in fam) == (best[1][0]["slot"] in fam):
        return None                                   # still ambiguous: don't guess
    return best[0][0]


KNOWN_TYPES = {"BEAM", "COLUMN", "VERTICAL BRACE", "HORIZONTAL BRACE", "MISC", "STAIR", "JOIST", "Wall", "Ref Point",
               "PL GIRDER", "ANGLE", "KICKER", "EMBED", "GRATING", "DECKING", "HANDRAIL", "STAIR STRINGER",
               "DWF Import", "IFC Import", "SDNF Import", "DGN Import", "Reference Model", "ReferenceModel"}
# members that hold an imported reference model (DWF / IFC import): one member file places thousands of piece files
# that have no piece-table entry (data-3 SDS_Jobs_2015.25 / 7.331 jobs.7z: 50 of 71 jobs are such models)
REFERENCE_TYPES = {"DWF Import", "IFC Import", "SDNF Import", "DGN Import", "Reference Model", "ReferenceModel"}
# the spelling varies by version: 7.720 "IFC_RH Palo_Grand Stair" stores "REFERENCE MODEL" (44 placements of curved C15x40
# stringers with L = 0 / no weight -> written as straight extrusions [approx] instead of their stored B-rep)
REFERENCE_TYPES |= {t.upper() for t in REFERENCE_TYPES}
KNOWN_TYPES |= REFERENCE_TYPES


def _sparse_try(job, idx, ids, shapes, slot, ver):
    """One candidate slot size for sparse_layout -> (layout, typed members) or None."""
    # Fixed layouts documented/validated in README.md and the calibration corpus.  7.245 differs from the original
    # 7.243 sample by four bytes in the section field; do not extend that exception to other 7.2xx versions.
    fixed = {
        1280: dict(type=0x44, p1=0x10A, p2=0x13C, sec=0x16E, roll=0x172, fw=4),
        1416: dict(type=0x04, p1=0x10A, p2=0x13C, sec=0x16E, roll=0x172, fw=4),
        2944: dict(type=0xA78, p1=0x112, p2=0x186, sec=0x1FC, roll=0x202, fw=8),
        2976: dict(type=0xA98, p1=0x112, p2=0x186, sec=0x1FC, roll=0x202, fw=8),
    }.get(slot)
    if slot == 2494 and ver == "7.245":
        fixed = dict(type=0x988, p1=0x112, p2=0x172, sec=0x1D8, roll=0x1DE, fw=8)
    if slot in (3204, 3404, 3600):
        # Later families share the 7.4+ point/section fields.  Their type field moved with the slot width, so accept
        # it only when at least one real member marker identifies the offset (the failing 7.613 and 8.007 jobs do).
        pos = [m.start() for m in re.finditer(
            rb"(?<![ -~])(BEAM|COLUMN|VERTICAL BRACE|HORIZONTAL BRACE|MISC|STAIR|JOIST|Wall|Ref Point)\x00", idx)]
        offs = collections.Counter(p % slot for p in pos)
        if offs:
            fixed = dict(type=offs.most_common(1)[0][0], p1=0x112, p2=0x186,
                         sec=0x1FC, roll=0x202, fw=8)
    if fixed is None:
        return None
    L = dict(slot=slot, **fixed)
    if L["fw"] == 4 and not ALLOW_71:
        return None

    # Reject a coincidental slot match or wrong type offset before geometry code sees it.  Empty/sentinel records are
    # allowed, but at least one materialised member must have a printable type.  Structural records additionally need
    # finite, plausible end points and a real section-table entry.
    fmt, pl = (">3d", 24) if L["fw"] == 8 else (">3f", 12)
    typed = structural = 0
    for n in ids:
        s = idx[n * slot:(n + 1) * slot]
        if len(s) < slot:
            continue
        typ = _ascii(s[L["type"]:L["type"] + 32])
        if typ in KNOWN_TYPES:
            typed += 1
        if typ not in ("BEAM", "COLUMN", "VERTICAL BRACE", "HORIZONTAL BRACE"):
            continue
        structural += 1
        with np.errstate(all="ignore"):
            p1 = np.asarray(struct.unpack(fmt, s[L["p1"]:L["p1"] + pl]), dtype=float)
            p2 = np.asarray(struct.unpack(fmt, s[L["p2"]:L["p2"] + pl]), dtype=float)
        sec = struct.unpack(">h", s[L["sec"]:L["sec"] + 2])[0]
        if not np.isfinite(p1).all() or not np.isfinite(p2).all() or max(np.abs(p1).max(), np.abs(p2).max()) > 1e6:
            return None
        if sec not in shapes:
            return None
    return (L, typed) if typed else None


def read_members(job, layout=None):
    shapes = read_shapes(job)
    if layout is not None:
        L = layout
    else:
        try:
            L = calibrate(job, shapes)
        except ValueError:
            L = sparse_layout(job, shapes)
            if L is None:
                raise
    md = os.path.join(job, "mem")
    idx = open(os.path.join(md, "mem_idx"), "rb").read()
    ids = sorted(int(n) for n in os.listdir(md) if n.isdigit())
    fmt, pl = (">3d", 24) if L.get("fw", 8) == 8 else (">3f", 12)
    out = []
    for n in ids:
        s = idx[n * L["slot"]:(n + 1) * L["slot"]]
        if len(s) < L["slot"]:
            continue
        p1 = struct.unpack(fmt, s[L["p1"]:L["p1"] + pl])
        p2 = struct.unpack(fmt, s[L["p2"]:L["p2"] + pl])
        sec = struct.unpack(">h", s[L["sec"]:L["sec"] + 2])[0]
        if L["roll"] < 0:
            roll = 0.0
        elif L.get("fw", 8) == 8:
            roll = struct.unpack(">d", s[L["roll"]:L["roll"] + 8])[0]
        else:
            roll = struct.unpack(">f", s[L["roll"]:L["roll"] + 4])[0]
        if roll != roll or abs(roll) > 7:
            roll = 0.0
        out.append(Member(n, _ascii(s[L["type"]:L["type"] + 32]), p1, p2, shapes.get(sec), roll))
    return out, L
