"""STEP file integrity and text-level content, streamed (works on multi-GB files in constant memory)."""
import hashlib, re, collections

GZIP_MAGIC = b"\x1f\x8b"
ZIP_MAGIC = b"PK\x03\x04"
_ENT = re.compile(r"#(\d+)\s*=\s*([A-Z_][A-Z_0-9]*)\s*\(")
_UUID = re.compile(r"'product-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
GEOM_SCHEMA = re.compile(r"AP2(03|14|42)|CONFIG_CONTROL|AUTOMOTIVE_DESIGN|MANAGED_MODEL_BASED_3D_ENGINEERING", re.I)
SOLID_ENTS = ("FACETED_BREP", "MANIFOLD_SOLID_BREP", "BREP_WITH_VOIDS")
SURFACE_ENTS = ("SHELL_BASED_SURFACE_MODEL", "OPEN_SHELL", "FACE_BASED_SURFACE_MODEL")
COUNTED = SOLID_ENTS + SURFACE_ENTS + ("PRODUCT", "CLOSED_SHELL", "ADVANCED_FACE", "FACE_SURFACE", "TRIANGULATED_FACE", "POLY_LOOP")


def decode_step_string(s):
    """ISO 10303-21 string -> text: '' -> ', \\X2\\hhhh..\\X0\\, \\X\\hh, \\S\\c."""
    s = s.replace("''", "'")
    def x2(m):
        h = m.group(1); return "".join(chr(int(h[i:i + 4], 16)) for i in range(0, len(h), 4))
    s = re.sub(r"\\X2\\([0-9A-Fa-f]+)\\X0\\", x2, s)
    s = re.sub(r"\\X4\\([0-9A-Fa-f]+)\\X0\\", lambda m: "".join(chr(int(m.group(1)[i:i + 8], 16)) for i in range(0, len(m.group(1)), 8)), s)
    s = re.sub(r"\\X\\([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]).decode("latin-1"), s)
    s = re.sub(r"\\S\\(.)", lambda m: chr(ord(m.group(1)) + 128), s)
    return s


def _first_string(stmt):
    """First quoted string argument of a statement, honouring '' escapes."""
    i = stmt.find("'")
    if i < 0: return None
    j = i + 1; out = []
    while j < len(stmt):
        if stmt[j] == "'":
            if j + 1 < len(stmt) and stmt[j + 1] == "'": out.append("''"); j += 2; continue
            return "".join(out)
        out.append(stmt[j]); j += 1
    return None


def classify_writer(header):
    h = header or ""
    if "Tekla model.dmp to STEP converter" in h: return "tekla_dmp"
    if "ifc2step" in h: return "ifc2step"
    if "Open CASCADE" in h: return "ifcconvert_occ"
    if re.search(r"SDS/?2", h): return "sds2"
    return "other"


def scan(path):
    """-> dict with integrity, header, writer, units, entity counts, product names (ordered) and uuids (first-seen order)."""
    h = hashlib.sha256(); size = 0; head = b""; tail = b""
    with open(path, "rb") as f:
        while True:
            b = f.read(16 << 20)
            if not b: break
            if len(head) < 65536: head += b[:65536 - len(head)]
            h.update(b); size += len(b); tail = (tail + b)[-4096:]
    R = dict(bytes=size, sha256=h.hexdigest())
    lead = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    if size == 0: R["kind"] = "empty"
    elif head.startswith(GZIP_MAGIC) or head.startswith(ZIP_MAGIC): R["kind"] = "compressed"
    elif lead.startswith(b"ISO-10303-21"): R["kind"] = "step"
    else: R["kind"] = "not_step"
    R["end_marker"] = b"END-ISO-10303-21" in tail
    txt = head.decode("utf-8", "replace")
    hs, he = txt.find("HEADER;"), txt.find("ENDSEC;")
    header = txt[hs:he] if hs >= 0 and he > hs else ""
    R["header"] = " ".join(header.split())[:1000]
    fn = re.search(r"FILE_NAME\s*\((.*?)\)\s*;", header, re.S)
    R["file_name_args"] = " ".join(fn.group(1).split())[:500] if fn else None
    R["header_input_name"] = decode_step_string(_first_string(fn.group(1)) or "") if fn else None
    sc = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']*)'", header)
    R["schema"] = sc.group(1) if sc else None
    R["schema_class"] = ("none" if not sc else "geometry" if GEOM_SCHEMA.search(sc.group(1)) else
                         "cis2" if re.search(r"STRUCTURAL_FRAME|CIS", sc.group(1), re.I) else "other")
    R["writer"] = classify_writer(header)
    R["is_ifc_conversion"] = R["writer"] in ("ifc2step", "ifcconvert_occ")
    if R["kind"] != "step":
        R.update(entities={}, product_names=[], uuids=[], length_unit=None, entities_total=0); return R
    ents = collections.Counter(); names = []; uuids = []; seen = set(); unit = None
    buf = None                                        # statement being assembled (PRODUCT / LENGTH_UNIT span lines)
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            for m in _ENT.finditer(line): ents[m.group(2)] += 1
            if "'product-" in line:
                for m in _UUID.finditer(line):
                    if m.group(1) not in seen: seen.add(m.group(1)); uuids.append(m.group(1))
            if buf is None and ("PRODUCT(" in line.replace(" ", "") or "LENGTH_UNIT" in line):
                buf = ""
            if buf is not None:
                buf += line
                if ";" in line:
                    st = buf; buf = None
                    compact = st.replace(" ", "")
                    if re.search(r"=PRODUCT\(", compact):
                        n = _first_string(st[st.find("PRODUCT"):])
                        names.append(decode_step_string(n) if n is not None else "")
                    if unit is None and "LENGTH_UNIT" in st:
                        unit = "mm" if ".MILLI." in st else "m" if re.search(r"SI_UNIT\(\s*\$\s*,\s*\.METRE\.", st) else ("inch" if "INCH" in st.upper() else "other")
                elif len(buf) > 20000:                 # malformed statement: never let it swallow the file
                    buf = None
    R["entities"] = {k: ents[k] for k in COUNTED if ents[k]}
    R["entities_total"] = sum(ents.values())
    R["product_names"] = names; R["uuids"] = uuids; R["length_unit"] = unit
    R["solid_entities"] = sum(ents[k] for k in SOLID_ENTS); R["surface_entities"] = sum(ents[k] for k in SURFACE_ENTS)
    return R
