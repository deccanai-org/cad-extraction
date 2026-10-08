"""Piece (subm) table from subm/subm_idx (852-B slots 7.2/7.3, 902-B 7.4, 440-B f32 7.1; see LAYOUTS). 7.243:
  +0x110 i32 section index into job_mtrl (0 for plates/bars), +0x12E ASCII name (e.g. W18x35, L4x4x3/8, FL3/8x9),
  +0x144 f64 weight lb, +0x14C f64 surface area, +0x16C f64 length, +0x174 f64 width/depth, +0x17C f64 thickness.
Also classifies each placed instance and prints coverage stats."""
import os, re, struct, sys, collections

# slot size, name offset, section (fmt, off), weight/L/W/T (fmt, offsets)
LAYOUTS = {
    852: dict(name=0x12E, sec=(">i", 0x110), f=">d", wt=0x144, L=0x16C, W=0x174, T=0x17C),   # 7.2xx / 7.3xx
    902: dict(name=0x12E, sec=(">i", 0x110), f=">d", wt=0x144, L=0x16C, W=0x174, T=0x17C),   # 7.4xx (+metric name)
    # 7.5xx / 7.6xx: the 7.2 record shifted by 4 bytes in 1024-B slots (metric name at +642). 9 jobs, 35,063 pieces:
    # section 100%, T 99.9% of plate names; wt at +0x148 is the net weight (0x3F6 holds the nominal L x W x T one)
    1024: dict(name=0x132, sec=(">i", 0x114), f=">d", wt=0x148, L=0x170, W=0x178, T=0x180),
    # 7.1xx: 440-B slots, f32 fields. Validated on 7 jobs (5,721 pieces): section index 100% of 4,362 rolled pieces,
    # thickness 97% of plate names, weight = lb/ft x L / 12 for 91% of rolled pieces
    440: dict(name=0x11A, sec=(">h", 0x10A), f=">f", wt=0x130, L=0x146, W=0x14A, T=0x14E),
    # 7.0xx: 384-B slots, the 7.1 record with L/W/T 4 bytes earlier (SUNY 7.021 + RCMS 7.039, 3,345 pieces:
    # section 100% of rolled, T 99.5% of plates, weight = lb/ft x L / 12 for 99.7%)
    384: dict(name=0x11A, sec=(">h", 0x10A), f=">f", wt=0x130, L=0x142, W=0x146, T=0x14A),
    # 8.0xx (SDS2 2019+): 1024-B slots like 7.5/7.6, name moved to the record end (+0x3C0, metric +0x3D7) and the
    # numeric fields 0x14 earlier. SampleJob + Morgan State 8.007, 2,961 pieces: T 100% of plates, section 89%
    "8.0": dict(slot=1024, name=0x3C0, sec=(">i", 0x114), f=">d", wt=0x134, L=0x15C, W=0x164, T=0x16C),
}
for _k, _v in LAYOUTS.items():
    _v.setdefault("slot", _k)


def slot_size(b):
    """Pick the layout whose name field is filled for the most of the first 200 pieces. Returns the LAYOUTS key
    (the slot size, except "8.0" for the 2019+ record that shares 1024-B slots with 7.5/7.6)."""
    def filled(key):
        S, o = LAYOUTS[key]["slot"], LAYOUTS[key]["name"]
        return sum(bool(re.match(rb"[!-~]", b[k * S + o:k * S + o + 1])) for k in range(1, min(200, len(b) // S)))
    return max(LAYOUTS, key=filled)


def read_pieces(job):
    b = open(os.path.join(job, "subm", "subm_idx"), "rb").read()
    key = slot_size(b); Lo = LAYOUTS[key]; SLOT = Lo["slot"]
    fs = struct.calcsize(Lo["f"]); rd = lambda s, o: struct.unpack(Lo["f"], s[o:o + fs])[0]
    sf, so = Lo["sec"]
    out = {}
    for k in range(1, (len(b) - 256) // SLOT):
        s = b[k * SLOT:(k + 1) * SLOT]
        name = re.match(rb"[ -~]*", s[Lo["name"]:Lo["name"] + 0x30]).group().decode()
        if not name:
            continue
        sec = struct.unpack(sf, s[so:so + struct.calcsize(sf)])[0]
        out[k] = dict(name=name, sec=sec, L=rd(s, Lo["L"]), W=rd(s, Lo["W"]), T=rd(s, Lo["T"]), wt=rd(s, Lo["wt"]))
    return out


def kind(p):
    n = p["name"]
    if re.match(r"(FL|PL|BAR|RD|SQ)", n) or (p["sec"] == 0 and p["T"] > 0):
        return "plate"
    if p["sec"] > 0:
        return "rolled"
    return "other"


if __name__ == "__main__":
    from instances import material_instances
    job = sys.argv[1]
    P = read_pieces(job)
    print("pieces with names:", len(P), collections.Counter(kind(p) for p in P.values()))
    c = collections.Counter(); names = collections.Counter()
    for n in sorted(int(x) for x in os.listdir(os.path.join(job, "mem")) if x.isdigit()):
        for sid, M, o in material_instances(job, n)[1]:
            p = P.get(sid)
            c[kind(p) if p else "missing"] += 1
            if p and kind(p) == "other": names[p["name"]] += 1
    print("placed instances by kind:", c)
    print("'other' names:", names.most_common(15))
    print("examples:", [(k, v) for k, v in list(P.items())[:6]])
