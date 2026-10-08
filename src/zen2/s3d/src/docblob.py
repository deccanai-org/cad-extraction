"""Decode DRAWNGDocumentData.DataBlob (read-only)."""
import io, zipfile, zlib, struct


def decode(blob, compressed=True):
    b = bytes(blob)
    if b[:4] == b'PK\x03\x04':
        method, csize, usize, nlen, xlen = struct.unpack('<H8xII HH', b[8:30])
        name = b[30:30 + nlen].decode('latin1')
        start = 30 + nlen + xlen
        raw = b[start:start + csize] if csize else b[start:]
        if method == 9:
            import inflate64
            return inflate64.Inflater().inflate(raw), 'zip64d:' + name
        if method == 8:
            return zlib.decompress(raw, -15), 'zipd:' + name
        if method == 0:
            return raw, 'zip0:' + name
        z = zipfile.ZipFile(io.BytesIO(b))
        return z.read(z.namelist()[0]), 'zip:' + name
    if b[:4] == b'PK\x01\x02':               # central-directory style header + raw stream (like GEOTOP blobs)
        method = struct.unpack('<H', b[10:12])[0]
        raw = b[46:]
        if method == 8:
            return zlib.decompress(raw, -15), 'cd-deflate'
        if method == 9:
            import inflate64
            return inflate64.Inflater().inflate(raw), 'cd-deflate64'
        return raw, 'cd-stored'
    if compressed:
        for w in (15, -15, 31):
            try:
                return zlib.decompress(b, w), 'zlib%d' % w
            except Exception:
                pass
    return b, 'raw'


if __name__ == '__main__':
    import sys
    from common import connect, query, MDB
    c = connect(MDB)
    cols, rows = query(c, "SELECT TOP 3 CAST(oid AS char(36)), FileName, FileSize, FileCompressed, DataBlob FROM dbo.DRAWNGDocumentData WHERE FileType = '%s' ORDER BY oid" % (sys.argv[1] if len(sys.argv) > 1 else 'pcf'))
    for o, fn, fs, fc, blob in rows:
        b = bytes(blob)
        data, how = decode(b, fc)
        print(o, fn, 'declared', fs, 'stored', len(b), 'head', b[:8].hex(), '->', how, len(data))
        print(data[:600].decode('latin1'))
