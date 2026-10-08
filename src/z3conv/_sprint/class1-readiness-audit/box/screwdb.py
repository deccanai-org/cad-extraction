"""Tekla bolt catalogs shipped in model folders.
screwdb.db (gzip or raw): header i4 version, i4 count, i4 body size; records = 0x04 + body (stride body+1)
  v<=202 (Xsteel 4.x, body 88): name@1[32] d@33 L@37 std@41[12] type@53 i4@57 weight@61 p1..p6@65..85 (f4)
  v3     (Tekla 13+, body 116):  name@1[40] d@45 L@49 std@53[28] type@81 i4@85 weight@89 p1..p6@93..113 (f4)
  type 1/2/3 bolt (hex/cup/csk), 101 nut, 201 washer, 301 stud
  bolt: p1 head height k, p2 thread length, p4 head across flats s, p5 across corners e
  nut: p1 height m, p3 hole, p4 across flats, p5 across corners;  washer: p1 thickness, p3 inner d, p4 outer d
assdb.db: header i4 version, i4 count, i4 body; records 0x04 + body: assembly standard then component standards
  (bolt, nut1, nut2, washer1, washer2, washer3, ...) as fixed-width strings."""
import gzip, struct, re, sys, json
def raw(p):
    d = open(p, 'rb').read()
    return gzip.decompress(d) if d[:2] == b'\x1f\x8b' else d
def cs(b):
    e = b.find(b'\0'); return b[:e if e >= 0 else len(b)].decode('latin1').strip()
LAY = {88: dict(name=(1, 32), d=33, L=37, std=(41, 12), type=53, w=61, p=65),
       116: dict(name=(1, 40), d=45, L=49, std=(53, 28), type=81, w=89, p=93)}
def screws(p):
    d = raw(p); ver, n, body = struct.unpack('<3i', d[:12]); st = body + 1; L = LAY[body]; out = []
    for i in range(n):
        r = d[12 + i * st:12 + (i + 1) * st]
        if len(r) < st or r[0] != 4: break
        f = lambda k: struct.unpack('<f', r[k:k + 4])[0]
        out.append(dict(name=cs(r[L['name'][0]:L['name'][0] + L['name'][1]]), d=round(f(L['d']), 4), L=round(f(L['L']), 4),
                        std=cs(r[L['std'][0]:L['std'][0] + L['std'][1]]), type=struct.unpack('<i', r[L['type']:L['type'] + 4])[0],
                        weight=round(f(L['w']), 4), p=[round(f(L['p'] + 4 * j), 4) for j in range(6)]))
    return dict(version=ver, count=n, body=body, rows=out)
def assemblies(p):
    d = raw(p); ver, n, body = struct.unpack('<3i', d[:12]); st = body + 1; out = []
    for i in range(n):
        r = d[12 + i * st:12 + (i + 1) * st]
        if len(r) < st or r[0] != 4: break
        strs = [(m.start(), m.group().decode('latin1')) for m in re.finditer(rb'[\x20-\x7e]{2,}', r)]
        out.append(dict(raw=strs))
    return dict(version=ver, count=n, body=body, rows=out)
if __name__ == '__main__':
    s = screws(sys.argv[1]); print(s['version'], s['count'], s['body'])
    import collections
    print(collections.Counter(r['type'] for r in s['rows']))
    for pat in sys.argv[2:]:
        for r in s['rows']:
            if re.search(pat, r['name']): print(r)
