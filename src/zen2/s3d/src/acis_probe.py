import sys, io, struct, json, zlib
from common import *
import inflate64, olefile

def blob_to_sab(blob):
    # ZIP central-directory-style header (46 bytes) + Deflate64 stream -> OLE2 -> JS_TOPOLOGY_STREAM
    assert blob[:4] == b'PK\x01\x02', blob[:4]
    method = struct.unpack('<H', blob[10:12])[0]
    raw = blob[46:]
    if method == 9:
        d = inflate64.Inflater(); data = d.inflate(raw)
    elif method == 8:
        data = zlib.decompress(raw, -15)
    else:
        data = raw
    ole = olefile.OleFileIO(io.BytesIO(data))
    names = ['/'.join(e) for e in ole.listdir()]
    s = ole.openstream('JS_TOPOLOGY_STREAM').read()
    return s, names

oid = sys.argv[1]
c = connect(MDB)
cols, rows = query(c, "SELECT blob, blobSize, isCompressed FROM dbo.GEOTOPSolidBody WHERE oid = '%s'" % oid)
blob, bs, comp = rows[0]
blob = bytes(blob)
sab, names = blob_to_sab(blob)
print('stored', len(blob), 'blobSize', bs, 'ole streams', names, 'sab bytes', len(sab), sab[:40])
open('/data/s3d/tmp/probe.sab', 'wb').write(sab)
from ezdxf.acis import sab as S, api
try:
    recs = S.parse_sab(sab)
    print('parse_sab ok', type(recs))
except Exception as e:
    print('parse_sab fail', type(e).__name__, e)
try:
    bodies = api.load(sab)
    print('api.load ok bodies', len(bodies))
    for b in bodies:
        ms = api.mesh_from_body(b)
        for m in ms:
            print('mesh verts', len(m.vertices), 'faces', len(m.faces))
except Exception as e:
    import traceback; traceback.print_exc()
