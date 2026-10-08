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
STRUCT_TYPES = {"BEAM", "COLUMN", "VERTICAL BRACE", "HORIZONTAL BRACE", "JOIST", "GIRT", "PURLIN", "PL GIRDER"}
JOIST_NAME = re.compile(r"^\d+(K|LH|DLH|KCS|DL|G|BG|VG)\d*")
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


_MTRL_CACHE = {}


def mtrl_layout(job):
    """Self-calibrated job_mtrl layout (record size, base, byte order, field offsets) - see mtrl_calib.py.
    7.2xx/7.3xx: BE, 510-B records; 7.4xx: LE, 390-B records. Section field value v -> record at base + v*rec."""
    if job not in _MTRL_CACHE:
        from mtrl_calib import calibrate_mtrl
        b = open(os.path.join(job, "main", "job_mtrl"), "rb").read()
        try:
            _MTRL_CACHE[job] = (calibrate_mtrl(b), b)
        except ValueError as ex:
            raise ValueError(f"unsupported job_mtrl layout ({len(b)} bytes, {ex}) - version {read_version(job)}")
    return _MTRL_CACHE[job]


def read_shapes(job):
    L, b = mtrl_layout(job)
    e, rec, base, do, wo = L["endian"], L["rec"], L["base"], L["d_off"], L["weight_off"]
    ft = L.get("ftype", "d"); w = struct.calcsize(ft)
    out = {}
    for k in range((len(b) - base) // rec):
        r = b[base + k * rec: base + (k + 1) * rec]
        if len(r) < max(do + 5 * w, wo + w): continue
        d, bf, tf, tw, kk = struct.unpack(e + "5" + ft, r[do:do + 5 * w])
        wt = struct.unpack(e + ft, r[wo:wo + w])[0]
        out[k] = Shape(k, _ascii(r[:40]), d, bf, tf, tw, kk, wt)
    return out


def calibrate(job, shapes):
    md = os.path.join(job, "mem")
    idx = open(os.path.join(md, "mem_idx"), "rb").read()
    pos = [m.start() for m in re.finditer(rb"(?<![ -~])(BEAM|COLUMN|VERTICAL BRACE|MISC|Ref Point)\x00", idx)]
    if len(pos) < 3:        # prototype / clipboard / empty jobs (0-2 members): nothing to calibrate on (EC-50)
        raise ValueError(f"job has only {len(pos)} members in mem_idx - empty or placeholder job")
    slot = collections.Counter(pos[i + 1] - pos[i] for i in range(len(pos) - 1)).most_common(1)[0][0]
    toff = collections.Counter(p % slot for p in pos).most_common(1)[0][0]
    ids = sorted(int(n) for n in os.listdir(md) if n.isdigit())
    p1c = collections.Counter()
    for n in ids[:400]:
        with open(os.path.join(md, str(n)), "rb") as f:
            k = f.read(0x60)[0x48:0x60]
        if len(k) == 24 and any(k):
            j = idx[n * slot:(n + 1) * slot].find(k)
            if j >= 0: p1c[j] += 1
    beams0 = [n for n in ids if _ascii(idx[n * slot + toff:n * slot + toff + 20]) == "BEAM"]
    if p1c:
        pt = ">f8"
        p1 = p1c.most_common(1)[0][0]
        p2c = collections.Counter()
        with np.errstate(all="ignore"):
            for n in ids[:1500]:
                s = idx[n * slot:(n + 1) * slot]
                if len(s) < slot: continue
                a = np.frombuffer(s[p1:p1 + 24], dtype=">f8")
                for off in range(p1 + 24, min(slot - 24, p1 + 400), 2):
                    q = np.frombuffer(s[off:off + 24], dtype=">f8")
                    if not np.isfinite(q).all() or np.abs(q).max() > 1e6: continue
                    dd = q - a; L = np.linalg.norm(dd)
                    if 12 < L < 5000 and np.sum(np.abs(dd) < 1e-3) >= 2:
                        p2c[off] += 1
        p2 = p2c.most_common(1)[0][0]
    else:
        # 7.0/7.1: mem/<n> records do not carry the work point, and points are 32-bit floats (EC-48).
        # Search the slot directly for the pair of 3-vector offsets that behaves like beam end points.
        pt, p1, p2 = _pair_search(idx, slot, beams0[:300] or ids[:300])
    # section field: i16 whose values map beams to real shape families with many distinct values
    # Searched over the whole slot after p2, in several integer formats (7.2/7.3 use BE i16 at p2+0x62 / p2+0x76;
    # 7.4xx differs). Score = share of beams mapped to a real, *named* shape family x diversity, penalised when one
    # section dominates (the constant-offset trap, EC-09).
    beams = [n for n in ids if _ascii(idx[n * slot + toff:n * slot + toff + 20]) == "BEAM"][:3000]
    if len(beams) < 20:          # joist-roofed / column-only jobs: sample every structural type (EC-49)
        beams = [n for n in ids if _ascii(idx[n * slot + toff:n * slot + toff + 20]) in STRUCT_TYPES][:3000]
    best = None
    fmts = ((">h", 2), ("<h", 2), (">i", 4), ("<i", 4))
    for so in range(p2 + 24, min(slot - 4, p2 + 0x300), 2):
        for fmt, w in fmts:
            vals = [struct.unpack(fmt, idx[n * slot + so:n * slot + so + w])[0] for n in beams]
            if not vals: continue
            ok = [v for v in vals if v in shapes and shapes[v].name and (shapes[v].family in SHAPE_FAMILIES or JOIST_NAME.match(shapes[v].name))]
            if not ok: continue
            top = collections.Counter(ok).most_common(1)[0][1] / len(ok)
            score = len(ok) / len(vals) * min(len(set(ok)), 20) * (0.2 if top > 0.8 and len(vals) > 50 else 1.0)
            if best is None or score > best[0] + 1e-9:
                best = (score, so, fmt)
    if best is None:
        raise ValueError("section field not found")
    _, so, fmt = best
    # a 4-byte read whose high half is always zero is the same field as the 2-byte one inside it; normalise to the
    # 2-byte field so the derived roll offset (field + 6) stays where it was validated on 7.2xx/7.3xx
    if fmt == ">i" and all(idx[n * slot + so:n * slot + so + 2] == b"\0\0" for n in beams[:500]):
        so, fmt = so + 2, ">h"
    elif fmt == "<i" and all(idx[n * slot + so + 2:n * slot + so + 4] == b"\0\0" for n in beams[:500]):
        fmt = "<h"
    roll = so + 6
    if pt == ">f4":
        roll = _roll_search(idx, slot, toff, ids, p2) or roll
    return dict(slot=slot, type=toff, p1=p1, p2=p2, pt_fmt=pt, sec=so, sec_fmt=fmt, roll=roll)


def _pair_search(idx, slot, sample):
    """Find (dtype, p1, p2): two 3-vector offsets whose difference looks like a beam (12..5000 in long, with at least
    two coordinates equal, i.e. level and axis-aligned) for most sampled beams."""
    best = None
    for dt, w in ((">f8", 8), (">f4", 4)):
        cands = []
        with np.errstate(all="ignore"):
            for o in range(0, slot - 3 * w, 2):
                V = np.array([np.frombuffer(idx[n * slot + o:n * slot + o + 3 * w], dtype=dt) for n in sample], dtype=float)
                ok = np.isfinite(V).all(1) & (np.abs(V) < 1e6).all(1) & ((np.abs(V) > 1e-3).sum(1) >= 2)
                if ok.mean() > 0.6 and np.nanstd(V[ok], 0).max() > 1:
                    cands.append((o, V))
        for i, (a, VA) in enumerate(cands):
            for b, VB in cands[i + 1:]:
                if b - a < 3 * w: continue
                D = VB - VA; L = np.linalg.norm(D, axis=1)
                good = (L > 12) & (L < 5000) & ((np.abs(D) < 1e-2).sum(1) >= 2)
                sc = float(good.mean())
                if best is None or sc > best[0] + 1e-9:
                    best = (sc, dt, a, b)
    if best is None or best[0] < 0.5:
        raise ValueError("work-point fields not found")
    return best[1], best[2], best[3]


def _roll_search(idx, slot, toff, ids, after):
    """f32 roll field: columns carry 0 / +-pi/2 / +-pi, with a real share of non-zero values."""
    cols = [n for n in ids if _ascii(idx[n * slot + toff:n * slot + toff + 20]) == "COLUMN"][:300]
    if len(cols) < 5: return None
    best = None
    for o in range(after, slot - 4, 2):
        v = np.array([struct.unpack(">f", idx[n * slot + o:n * slot + o + 4])[0] for n in cols])
        with np.errstate(all="ignore"):
            q = np.isclose(np.abs(v), 0, atol=1e-4) | np.isclose(np.abs(v), np.pi / 2, atol=1e-3) | np.isclose(np.abs(v), np.pi, atol=1e-3)
        nz = np.mean(np.abs(v) > 1e-3)
        if q.mean() > 0.9 and 0.05 < nz < 0.95:
            sc = q.mean() + nz
            if best is None or sc > best[0]: best = (sc, o)
    return best[1] if best else None


NAME_RX = re.compile(rb"(?<![ -~])((?:W|HSS|L|C|MC|WT|S|HP|PIPE|TS|FL|PL|BPL)\d[\dxX./ -]*)\x00")
NAME_AT = re.compile(rb"(?:W|HSS|L|C|MC|WT|S|HP|PIPE|TS|FL|PL|BPL)\d[\dxX./ -]*\x00")


def piece_name_path(job, ids, sample=400):
    """Member -> main-material piece (mem/<n> +0xE8, BE i32) -> subm/subm_idx slot -> section name (ASCII).
    Slot size and name offset are calibrated: the slot size is the one at which the name strings line up, and the
    name offset is the one where the main pieces of sampled members land on a valid section name.
    Returns (dict member -> name, layout) or ({}, None)."""
    p = os.path.join(job, "subm", "subm_idx")
    if not os.path.exists(p):
        return {}, None
    sb = open(p, "rb").read()
    pos = [m.start() for m in NAME_RX.finditer(sb)]
    if len(pos) < 50:
        return {}, None
    pid = {}
    for n in ids[:sample]:
        with open(os.path.join(job, "mem", str(n)), "rb") as f:
            b = f.read(0xEC)
        if len(b) >= 0xEC:
            pid[n] = struct.unpack(">i", b[0xE8:0xEC])[0]
    best = None
    for S in range(400, 1600, 2):
        X, c = collections.Counter(q % S for q in pos).most_common(1)[0]
        if c < 0.2 * len(pos): continue           # names do not line up at this slot size
        hits = sum(1 for v in pid.values() if 0 < v and (v * S + X + 2) < len(sb) and NAME_AT.match(sb, v * S + X))
        if best is None or hits > best[0]:
            best = (hits, S, X)
    hits, S, X = best
    if hits < 0.5 * max(1, len(pid)):
        return {}, None
    out = {}
    for n in ids:
        with open(os.path.join(job, "mem", str(n)), "rb") as f:
            b = f.read(0xEC)
        if len(b) < 0xEC: continue
        v = struct.unpack(">i", b[0xE8:0xEC])[0]
        if v > 0 and v * S + X < len(sb):
            nm = _ascii(sb[v * S + X:v * S + X + 40])
            if nm: out[n] = nm
    return out, dict(slot=S, name_off=X, sample_hits=f"{hits}/{len(pid)}")


def read_members(job, layout=None):
    shapes = read_shapes(job)
    L = layout or calibrate(job, shapes)
    md = os.path.join(job, "mem")
    idx = open(os.path.join(md, "mem_idx"), "rb").read()
    ids = sorted(int(n) for n in os.listdir(md) if n.isdigit())
    out = []
    for n in ids:
        s = idx[n * L["slot"]:(n + 1) * L["slot"]]
        if len(s) < L["slot"]:
            continue
        pf = ">3f" if L.get("pt_fmt") == ">f4" else ">3d"; w = struct.calcsize(pf)
        p1 = struct.unpack(pf, s[L["p1"]:L["p1"] + w])
        p2 = struct.unpack(pf, s[L["p2"]:L["p2"] + w])
        fmt = L.get("sec_fmt", ">h")
        sec = struct.unpack(fmt, s[L["sec"]:L["sec"] + struct.calcsize(fmt)])[0]
        rf = ">f" if L.get("pt_fmt") == ">f4" else ">d"
        roll = struct.unpack(rf, s[L["roll"]:L["roll"] + struct.calcsize(rf)])[0]
        if roll != roll or abs(roll) > 7:
            roll = 0.0
        out.append(Member(n, _ascii(s[L["type"]:L["type"] + 32]), p1, p2, shapes.get(sec), roll))
    # cross-check / fallback: section by main-material piece name (independent of the section index field)
    if "sec_source" not in L:
        names, pl = piece_name_path(job, ids)
        by_name = {}
        for sh in shapes.values():
            by_name.setdefault(sh.name, sh)
        # The piece at +0xE8 is the member's FIRST material, usually the main shape but sometimes a connection
        # plate (FL/PL/BPL): only rolled-shape names say anything about the member's section.
        rolled = lambda nm: not re.match(r"(FL|PL|BPL|BAR|RD|SQ)", nm or "")
        st = [m for m in out if m.type in ("BEAM", "COLUMN", "VERTICAL BRACE", "HORIZONTAL BRACE") and rolled(names.get(m.id))
              and m.id in names]
        agree = sum(1 for m in st if m.section and m.section.name == names[m.id]) / len(st) if st else None
        L["piece_name_path"] = pl; L["index_vs_name_agreement"] = round(agree, 4) if agree is not None else None
        L["sec_source"] = "index"
        # fall back to names only when the index path is clearly broken (sections unnamed or one section dominates)
        structural = [m for m in out if m.type in ("BEAM", "COLUMN", "VERTICAL BRACE", "HORIZONTAL BRACE")]
        named = [m for m in structural if m.section and m.section.name]
        top = collections.Counter(m.section.name for m in named).most_common(1)[0][1] / len(named) if named else 1
        broken = not structural or len(named) / len(structural) < 0.8 or (len(structural) > 50 and top > 0.8)
        if broken and st:
            L["sec_source"] = "piece_name (index path broken)"
            for m in out:
                nm = names.get(m.id)
                if nm and rolled(nm) and nm in by_name:
                    m.section = by_name[nm]
                elif m.section is not None and not m.section.name:
                    m.section = None
    return out, L
