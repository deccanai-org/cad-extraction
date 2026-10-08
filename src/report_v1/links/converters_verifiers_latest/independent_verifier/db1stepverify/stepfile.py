"""STEP file integrity and text-level content, streamed (constant memory on multi-GB files)."""
import hashlib, re, collections

_ENT = re.compile(r"#(\d+)\s*=\s*([A-Z_][A-Z_0-9]*)\s*\(")
COUNTED = ("PRODUCT", "FACETED_BREP", "MANIFOLD_SOLID_BREP", "BREP_WITH_VOIDS", "CLOSED_SHELL", "OPEN_SHELL",
           "SHELL_BASED_SURFACE_MODEL", "ADVANCED_FACE", "FACE", "POLY_LOOP", "CARTESIAN_POINT",
           "TESSELLATED_SOLID", "TESSELLATED_SHELL", "TRIANGULATED_FACE_SET", "SHAPE_REPRESENTATION")


def decode_step_string(s):
    s = s.replace("''", "'")
    s = re.sub(r"\\X2\\([0-9A-Fa-f]+)\\X0\\", lambda m: "".join(chr(int(m.group(1)[i:i + 4], 16)) for i in range(0, len(m.group(1)), 4)), s)
    s = re.sub(r"\\X\\([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]).decode("latin-1"), s)
    return s


def _first_string(stmt):
    i = stmt.find("'")
    if i < 0: return None
    j = i + 1; out = []
    while j < len(stmt):
        if stmt[j] == "'":
            if j + 1 < len(stmt) and stmt[j + 1] == "'": out.append("''"); j += 2; continue
            return "".join(out)
        out.append(stmt[j]); j += 1
    return None


def scan(path):
    """-> integrity, header, schema, writer, units, entity counts, product names (file order)."""
    h = hashlib.sha256(); size = 0; head = b""; tail = b""
    with open(path, "rb") as f:
        while True:
            b = f.read(16 << 20)
            if not b: break
            if len(head) < 65536: head += b[:65536 - len(head)]
            h.update(b); size += len(b); tail = (tail + b)[-4096:]
    R = dict(bytes=size, sha256=h.hexdigest())
    lead = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    R["kind"] = ("empty" if size == 0 else "compressed" if head[:2] == b"\x1f\x8b" or head[:4] == b"PK\x03\x04"
                 else "step" if lead.startswith(b"ISO-10303-21") else "not_step")
    R["end_marker"] = b"END-ISO-10303-21" in tail
    txt = head.decode("utf-8", "replace")
    hs, he = txt.find("HEADER;"), txt.find("ENDSEC;")
    header = txt[hs:he] if hs >= 0 and he > hs else ""
    R["header"] = " ".join(header.split())[:800]
    fn = re.search(r"FILE_NAME\s*\((.*?)\)\s*;", header, re.S)
    R["header_input_name"] = decode_step_string(_first_string(fn.group(1)) or "") if fn else None
    sc = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']*)'", header)
    R["schema"] = sc.group(1) if sc else None
    R["writer"] = "ifc2step" if "ifc2step" in header else ("other" if header else None)
    if R["kind"] != "step":
        R.update(entities={}, product_names=[], length_unit=None, entities_total=0); return R
    ents = collections.Counter(); names = []; unit = None; buf = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            for m in _ENT.finditer(line): ents[m.group(2)] += 1
            if buf is None and ("PRODUCT(" in line or "LENGTH_UNIT" in line): buf = ""
            if buf is not None:
                buf += line
                if ";" in line:
                    st = buf; buf = None
                    if re.search(r"=\s*PRODUCT\(", st):
                        n = _first_string(st[st.find("PRODUCT"):]); names.append(decode_step_string(n) if n is not None else "")
                    if unit is None and "LENGTH_UNIT" in st:
                        unit = "mm" if ".MILLI." in st else "m" if re.search(r"SI_UNIT\(\s*\$\s*,\s*\.METRE\.", st) else "other"
                elif len(buf) > 20000: buf = None
    R["entities"] = {k: ents[k] for k in COUNTED if ents[k]}
    R["entities_total"] = sum(ents.values())
    R["product_names"] = names; R["length_unit"] = unit
    return R
