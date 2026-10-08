"""S3D GEOTOP blob -> ACIS SAB -> ezdxf ACIS entities -> polygon meshes (planar faces).

Blob: ZIP central-directory-style header + Deflate64 -> OLE2 compound file -> stream JS_TOPOLOGY_STREAM = SAB (ACIS 23-26).
S3D specifics handled here (ezdxf rejects the raw stream):
  * extra header fields after the tolerances (a bool + a 52-char id string) -> skipped
  * entity-type names are interned: first use 'name%<int32 id>', later uses '%<int32 id>' -> resolved per file
"""
import io, struct, zlib
import olefile
import ezdxf.acis.sab as S
from ezdxf.acis import const as C

ENT = S.Tags.ENTITY_TYPE
ENT_EX = S.Tags.ENTITY_TYPE_EX

_orig_read_header = S.Decoder.read_header


def _read_header(self):
    h = _orig_read_header(self)
    guard = 0
    while self.has_data and self.data[self.index] not in (ENT,) and guard < 20:
        tag = self.read_byte()
        if tag in (S.Tags.STR,):
            self.read_bytes(self.read_byte())
        elif tag == S.Tags.DOUBLE:
            self.read_float()
        elif tag in (S.Tags.INT, S.Tags.POINTER):
            self.read_int()
        guard += 1
    self._s3d_names = {}
    return h


def _resolve(self, s):
    if '%' not in s:
        return s
    i = s.index('%')
    name, idb = s[:i], s[i + 1:i + 5]
    try:
        nid = int.from_bytes(idb.encode('latin1'), 'little')
    except Exception:
        return name or s
    tab = getattr(self, '_s3d_names', None)
    if tab is None:
        tab = self._s3d_names = {}
    if name:
        tab[nid] = name
        return name
    return tab.get(nid, s)


_orig_read_str = S.Decoder.read_str


def _patched_read_record(self):
    # copy of ezdxf's read_record with name resolution for ENTITY_TYPE / ENTITY_TYPE_EX
    def entity_type_name():
        return "-".join(entity_type)
    values = []
    entity_type = []
    subtype_level = 0
    while True:
        if not self.has_data:
            if values:
                token = values[0]
                if token.value in C.DATA_END_MARKERS:
                    return values
            raise S.ParsingError("pre-mature end of data")
        tag = self.read_byte()
        T = S.Tags
        if tag == T.INT:
            values.append(S.Token(tag, self.read_int()))
        elif tag == T.DOUBLE:
            values.append(S.Token(tag, self.read_float()))
        elif tag == T.STR:
            values.append(S.Token(tag, self.read_bytes(self.read_byte()).decode('latin1')))
        elif tag == T.POINTER:
            values.append(S.Token(tag, self.read_int()))
        elif tag == T.BOOL_TRUE:
            values.append(S.Token(tag, True))
        elif tag == T.BOOL_FALSE:
            values.append(S.Token(tag, False))
        elif tag == T.LITERAL_STR:
            values.append(S.Token(tag, self.read_bytes(self.read_int()).decode('latin1')))
        elif tag == T.ENTITY_TYPE_EX:
            entity_type.append(_resolve(self, self.read_bytes(self.read_byte()).decode('latin1')))
        elif tag == T.ENTITY_TYPE:
            entity_type.append(_resolve(self, self.read_bytes(self.read_byte()).decode('latin1')))
            values.append(S.Token(T.ENTITY_TYPE, entity_type_name()))
            entity_type.clear()
        elif tag == T.LOCATION_VEC:
            values.append(S.Token(tag, self.read_floats(3)))
        elif tag == T.DIRECTION_VEC:
            values.append(S.Token(tag, self.read_floats(3)))
        elif tag == T.ENUM:
            values.append(S.Token(tag, self.read_int()))
        elif tag == T.UNKNOWN_0x17:
            values.append(S.Token(tag, self.read_float()))
        elif tag == T.SUBTYPE_START:
            subtype_level += 1
            values.append(S.Token(tag, subtype_level))
        elif tag == T.SUBTYPE_END:
            values.append(S.Token(tag, subtype_level))
            subtype_level -= 1
        elif tag == T.RECORD_END:
            return values
        else:
            raise S.ParsingError("unknown SAB tag: 0x%x (%d) in entity '%s'" % (tag, tag, values[0].value if values else '?'))


S.Decoder.read_header = _read_header
S.Decoder.read_record = _patched_read_record


def blob_to_sab(blob):
    b = bytes(blob)
    if b[:4] == b'PK\x01\x02':
        method = struct.unpack('<H', b[10:12])[0]
        raw = b[46:]
        if method == 9:
            import inflate64
            data = inflate64.Inflater().inflate(raw)
        elif method == 8:
            data = zlib.decompress(raw, -15)
        else:
            data = raw
    else:
        data = b
    if data[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
        ole = olefile.OleFileIO(io.BytesIO(data))
        return ole.openstream('JS_TOPOLOGY_STREAM').read()
    return data


def load(sab):
    from ezdxf.acis import api
    return api.load(sab)


def meshes(sab):
    """-> list of (vertices[list of xyz], faces[list of index lists]) in metres (SAB is mm-scaled units: 1 unit = 1000 mm)"""
    from ezdxf.acis import api
    out = []
    for body in api.load(sab):
        for m in api.mesh_from_body(body):
            out.append(([tuple(v) for v in m.vertices], [list(f) for f in m.faces]))
    return out


# ACIS 26 (S3D v2016+) writes some null references (e.g. the entity 'pattern') as INT -1 instead of POINTER -1
_Loader = S.SabDataLoader


def _read_ptr(self):
    token = self.data[self.index]
    if token.tag == S.Tags.POINTER:
        self.index += 1
        return token.value
    if token.tag == S.Tags.INT and token.value == -1:
        self.index += 1
        return S.NULL_PTR
    raise S.ParsingError("expected pointer token, got %s" % (token,))


_Loader.read_ptr = _read_ptr


def _build_entities(records, version):
    # like ezdxf's build_entities, but S3D/ACIS R26 records carry an extra INT (-1) after the id, before the pattern pointer
    for record in records:
        assert record[0].tag == ENT, "invalid entity-name tag"
        name = record[0].value
        if name in C.DATA_END_MARKERS:
            yield S.SabEntity(name)
            return
        attr = record[1].value
        id_ = record[2].value if record[2].tag == S.Tags.INT else -1
        data = record[3:] if record[2].tag == S.Tags.INT else record[2:]
        if len(data) >= 2 and data[0].tag == S.Tags.INT and data[1].tag == S.Tags.POINTER:
            data = data[1:]
        yield S.SabEntity(name, attr, id_, data)


S.build_entities = _build_entities
