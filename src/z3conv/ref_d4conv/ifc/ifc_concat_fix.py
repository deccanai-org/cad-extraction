"""Repair a concatenated STEP-21 IFC (several ISO-10303-21 HEADER/DATA blocks in one file, later blocks
reusing entity ids): merge every block into ONE exchange structure, renumbering each later block's
instance ids (and all references to them, never inside string literals) past the ids already used.
Refuses (returns reason) when blocks disagree on FILE_SCHEMA or on the length unit, since one merged
file would then scale part of the geometry wrongly.
Usage: ifc_concat_fix.py in.ifc out.ifc   -> prints JSON report"""
import json, re, sys
RID = re.compile(rb"#(\d+)")
RDEF = re.compile(rb"\s*#(\d+)\s*=")
RSCHEMA = re.compile(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']*)'", re.I)
RLEN = re.compile(rb"IFCSIUNIT\s*\(\s*\*\s*,\s*\.LENGTHUNIT\.\s*,\s*(\$|\.[A-Z]+\.)\s*,\s*\.METRE\.", re.I)
RCONV = re.compile(rb"IFCCONVERSIONBASEDUNIT\s*\([^;]*?\.LENGTHUNIT\.\s*,\s*'([^']*)'", re.I)
RPROJ = re.compile(rb"\s*#(\d+)\s*=\s*IFCPROJECT\s*\(", re.I)

def instances(fh):
    """yield ('kw', line) for section keywords, ('ent', bytes) for complete instances (quote-aware)"""
    buf = b""; quotes = 0
    for raw in fh:
        line = raw.rstrip(b"\r\n")
        if not buf:
            s = line.strip()
            if s in (b"ISO-10303-21;", b"HEADER;", b"DATA;", b"ENDSEC;", b"END-ISO-10303-21;") or not s:
                yield ("kw", s); continue
        buf = buf + (b"\n" if buf else b"") + line
        quotes += line.count(b"'")
        if quotes % 2 == 0 and buf.rstrip().endswith(b";"):
            yield ("ent", buf); buf = b""; quotes = 0
    if buf: yield ("ent", buf)

def shift_refs(ent, off, remap):
    parts = ent.split(b"'")
    def sub(m):
        i = int(m.group(1))
        return b"#%d" % (remap[i] if i in remap else i + off)
    for i in range(0, len(parts), 2):          # even segments are outside string literals
        parts[i] = RID.sub(sub, parts[i])
    return b"'".join(parts)

def fix(src, dst):
    blocks = []; cur = None; state = None
    with open(src, "rb") as fh:
        for kind, x in instances(fh):
            if kind == "kw":
                if x == b"HEADER;": cur = {"header": [], "n": 0, "max": 0, "min": None, "schema": None, "len": set(), "proj": []}; blocks.append(cur); state = "H"
                elif x == b"DATA;":
                    if cur is None: cur = {"header": [], "n": 0, "max": 0, "min": None, "schema": None, "len": set(), "proj": []}; blocks.append(cur)
                    state = "D"
                elif x == b"ENDSEC;": state = None
                continue
            if state == "H":
                cur["header"].append(x); m = RSCHEMA.search(x)
                if m: cur["schema"] = m.group(1).upper()
            elif state == "D":
                m = RDEF.match(x)
                if m:
                    i = int(m.group(1)); cur["n"] += 1; cur["max"] = max(cur["max"], i); cur["min"] = i if cur["min"] is None else min(cur["min"], i)
                if RPROJ.match(x): cur["proj"].append(int(RPROJ.match(x).group(1)))
                u = RLEN.search(x)
                if u: cur["len"].add(u.group(1).upper())
                c = RCONV.search(x)
                if c: cur["len"].add(b"CONV:" + c.group(1).upper())
    rep = {"blocks": [{"entities": b["n"], "min_id": b["min"], "max_id": b["max"], "schema": (b["schema"] or b"").decode(), "length_units": sorted(u.decode() for u in b["len"]), "projects": len(b["proj"])} for b in blocks]}
    if len(blocks) < 2: rep["result"] = "not_concatenated"; return rep
    if len({b["schema"] for b in blocks}) != 1: rep["result"] = "refused_schema_mismatch"; return rep
    units = [b["len"] for b in blocks if b["len"]]
    if len({frozenset(u) for u in units}) > 1 or any(len(u) != 1 for u in units): rep["result"] = "refused_unit_mismatch"; return rep
    if any(len(b["proj"]) != 1 for b in blocks): rep["result"] = "refused_project_count"; return rep
    # one IfcProject in the merged file (ifcopenshell takes the length unit from THE project; with two it
    # silently falls back to metres): later blocks' project instances are dropped and every reference
    # to them is re-pointed to the first block's project (units verified identical above)
    overlap = any(blocks[k]["min"] is not None and blocks[k]["min"] <= max(b["max"] for b in blocks[:k]) for k in range(1, len(blocks)))
    rep["ids_overlap"] = overlap
    offs = []; used = 0
    for b in blocks: offs.append(used if (overlap and used) else 0); used = max(used, (offs[-1] + b["max"]))
    if not overlap: offs = [0] * len(blocks)
    with open(src, "rb") as fh, open(dst, "wb") as out:
        out.write(b"ISO-10303-21;\nHEADER;\n")
        for h in blocks[0]["header"]: out.write(h + b"\n")
        out.write(b"ENDSEC;\nDATA;\n")
        k = -1; state = None; n = 0
        for kind, x in instances(fh):
            if kind == "kw":
                if x == b"HEADER;": k += 1; state = "H"
                elif x == b"DATA;":
                    if k < 0: k = 0
                    state = "D"
                elif x == b"ENDSEC;": state = None
                continue
            if state == "D":
                if k > 0:
                    m = RPROJ.match(x)
                    if m and int(m.group(1)) == blocks[k]["proj"][0]: continue
                    x = shift_refs(x, offs[k], {blocks[k]["proj"][0]: blocks[0]["proj"][0]})
                out.write(x + b"\n"); n += 1
        out.write(b"ENDSEC;\nEND-ISO-10303-21;\n")
    rep["result"] = "merged"; rep["offsets"] = offs; rep["entities_written"] = n
    return rep

if __name__ == "__main__":
    print(json.dumps(fix(sys.argv[1], sys.argv[2])))
