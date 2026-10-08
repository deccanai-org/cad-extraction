"""Independent ground truth for a job, all normalised to inches and canonical section names.

  IFC  : SDS2's own IFC export -> element AABBs (site coords; aligned later), type, piecemark, section
  KISS : .kss bill of materials -> (section, length) per line with quantity
  NC1  : DSTV CNC part files -> (piecemark, section, length, holes)
Edge cases handled: NC1/KISS lengths are mm; section spellings vary (W30X99 / W30x99 / 'L4x3 1/2x3/8');
IFC length unit read from the file (SDS2 writes METRE with large site offsets); IFC repeats some elements
(same piecemark twice) - kept, matching is one-to-one so repeats cannot inflate recall.
"""
import os, re, csv, glob, json

MM = 25.4


def _num(tok):
    """'4 1/2' -> 4.5, '3/8' -> 0.375, '.500' -> 0.5, '12' -> 12.0; returns None if not numeric."""
    tok = tok.strip()
    m = re.fullmatch(r"(\d+)(?:\s+|-)(\d+)/(\d+)", tok)          # '4 1/2' and '2-1/2'
    if m: return int(m[1]) + int(m[2]) / int(m[3])
    m = re.fullmatch(r"(\d+)/(\d+)", tok)
    if m: return int(m[1]) / int(m[2])
    try: return float(tok)
    except ValueError: return None


def canon(sec):
    """Canonical section: family prefix + dimensions as trimmed decimals joined by 'X'.
    'HSS12x12x1/2' == 'HSS12X12X.500', 'L4x3 1/2x3/8' == 'L4X3.5X.375', 'W30X99' == 'W30x99' (EC-31)."""
    s = (sec or "").strip().upper()
    m = re.match(r"^([A-Z]+)\s*(.*)$", s)
    if not m or not m[2]:
        return s.replace(" ", "")
    fam, rest = m[1], m[2]
    parts = [p for p in re.split(r"X", rest) if p.strip()]
    vals = [_num(p) for p in parts]
    if any(v is None for v in vals):
        return s.replace(" ", "")
    # round hollow sections: KISS 'PI8.625X0.375', SDS2 'HSS8.625x0.375' / 'PIPE...' (2 dims) -> ROUND (EC-31)
    if fam in ("PI", "PIPE", "HSS", "TS", "P") and len(vals) == 2:
        fam = "ROUND"
    if fam == "TS": fam = "HSS"
    return fam + "X".join(f"{v:.4f}".rstrip("0").rstrip(".") for v in vals)


# ---------------- KISS ----------------
def read_kiss(paths):
    """KISS 1.1 'D' lines: D,assembly,?,piece mark,material mark,qty,shape,size,grade,length(mm),..."""
    out = []
    for p in paths:
        for line in open(p, encoding="latin-1", errors="replace"):
            f = line.rstrip("\r\n").split(",")
            if f[0] != "D" or len(f) < 10:
                continue
            try:
                qty = int(float(f[5] or 1)); L = float(f[9]) / MM
            except ValueError:
                continue
            shape, size = f[6].strip(), f[7].strip()
            out.append(dict(src=os.path.basename(p), mark=f[3], material=f[4], qty=qty, kind=(f[12].strip().upper() if len(f) > 12 else ""),
                            section=canon(shape + size if not size.upper().startswith(shape.upper()) else size), length=L))
    return out


# ---------------- NC1 ----------------
def read_nc1(paths):
    """DSTV NC1 header (after 'ST'): order, drawing, phase, piece mark, grade, qty, profile, code, length(mm), ...
    Hole count = number of lines inside BO blocks."""
    out = []
    for p in paths:
        try:
            lines = [l.rstrip("\r\n") for l in open(p, encoding="latin-1", errors="replace")]
        except OSError:
            continue
        if not lines or lines[0].strip() != "ST":
            continue
        h = [l.strip() for l in lines[1:12]]
        try:
            qty = int(float(h[5] or 1)); L = float(h[8]) / MM
        except (ValueError, IndexError):
            continue
        holes, inbo = 0, False
        for l in lines[12:]:
            t = l.strip()
            if re.fullmatch(r"[A-Z]{2}", t):
                inbo = (t == "BO"); continue
            if inbo and t:
                holes += 1
        out.append(dict(src=os.path.basename(p), mark=h[3], qty=qty, section=canon(h[6]), code=h[7], length=L, holes=holes))
    return out


# ---------------- IFC ----------------
def read_ifc(path, use_cache=True):
    cache = path + ".elements.json"
    if use_cache and os.path.exists(cache) and os.path.getmtime(cache) > os.path.getmtime(path):
        return json.load(open(cache))
    import multiprocessing
    import numpy as np
    import ifcopenshell, ifcopenshell.geom, ifcopenshell.util.element as ue, ifcopenshell.util.unit as uu
    f = ifcopenshell.open(path)
    to_in = uu.calculate_unit_scale(f) / 0.0254          # file length unit -> inches
    els = [e for e in f.by_type("IfcElement") if not e.is_a("IfcElementAssembly")]
    s = ifcopenshell.geom.settings(); s.set("use-world-coords", True)
    it = ifcopenshell.geom.iterator(s, f, multiprocessing.cpu_count(), include=els)
    rows = []
    if it.initialize():
        while True:
            sh = it.get(); e = f.by_guid(sh.guid)
            v = np.array(sh.geometry.verts).reshape(-1, 3) / 0.0254   # geometry iterator always yields metres
            g = ue.get_psets(e).get("SDS2_General", {})
            cls = e.is_a()
            kind = "member" if cls in ("IfcBeam", "IfcColumn", "IfcMember") else ("part" if cls in ("IfcDiscreteAccessory", "IfcPlate", "IfcBuildingElementProxy") else "other")
            rows.append(dict(cls=cls, kind=kind, piecemark=g.get("Member_Piecemark") or e.Name or "",
                             material_mark=g.get("Material_Piecemark") or "", section=canon(g.get("Cross_Section") or e.Description or ""),
                             material_type=g.get("Material_Type") or "", lo=v.min(0).tolist(), hi=v.max(0).tolist()))
            if not it.next():
                break
    out = dict(path=path, unit_to_in=to_in, elements=rows)
    if use_cache:
        json.dump(out, open(cache, "w"))
    return out


def discover(folder):
    """Find ground-truth files under a folder (a job's project folder / fab packages)."""
    g = lambda pat: sorted(glob.glob(os.path.join(folder, "**", pat), recursive=True))
    return dict(ifc=g("*.ifc"), kss=g("*.kss"), nc1=g("*.nc1"))

