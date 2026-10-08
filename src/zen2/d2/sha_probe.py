#!/usr/bin/env python3
"""sha_probe.py SHA_RELPATH PDF_RELPATH - structure probe of the .sha graphics streams:
per stream: size, byte entropy, zlib/deflate detection, count of plausible float64 sheet coordinates, and how many PDF
line endpoints (converted to metres, sheet origin lower-left) are found among those doubles."""
import collections, math, struct, sys, zlib, json
import numpy as np
import olefile, pymupdf

SRC = '/work/in/src/'
sha_rel, pdf_rel = sys.argv[1], sys.argv[2]
o = olefile.OleFileIO(SRC + sha_rel)

# PDF reference coordinates (metres, y up), rounded to 0.1 mm
d = pymupdf.open(SRC + pdf_rel)
pg = d[0]
H = pg.rect.height
ref = set()
for dr in pg.get_drawings():
    for it in dr['items']:
        if it[0] == 'l':
            for p in it[1:3]:
                ref.add((round(p.x * 25.4 / 72 / 1000, 4), round((H - p.y) * 25.4 / 72 / 1000, 4)))
refx = set(x for x, y in ref)
print('pdf endpoints', len(ref), 'sheet %.3f x %.3f m' % (pg.rect.width * 25.4 / 72000, H * 25.4 / 72000))


def entropy(b):
    if not b:
        return 0
    c = np.bincount(np.frombuffer(b, np.uint8), minlength=256).astype(float)
    p = c[c > 0] / len(b)
    return float(-(p * np.log2(p)).sum())


rows = []
tot = collections.Counter()
for s in o.listdir(streams=True, storages=False):
    n = '/'.join(s)
    b = o.openstream(n).read()
    if len(b) < 64:
        continue
    e = entropy(b)
    z = None
    for off in range(0, min(len(b) - 2, 64)):
        if b[off] == 0x78 and b[off + 1] in (0x01, 0x5e, 0x9c, 0xda):
            try:
                z = (off, len(zlib.decompressobj().decompress(b[off:off + 200000])))
                break
            except Exception:
                pass
    # doubles at every byte offset in plausible sheet range
    hits = 0
    pairs = 0
    matched = 0
    arr8 = [np.frombuffer(b[k:len(b) - ((len(b) - k) % 8)], '<f8') for k in range(8)]
    for k, a in enumerate(arr8):
        with np.errstate(all='ignore'):
            ok = np.isfinite(a) & (a > 0.0005) & (a < 1.2)
        hits += int(ok.sum())
        idx = np.nonzero(ok[:-1] & ok[1:])[0]
        pairs += len(idx)
        for i in idx[:200000]:
            if (round(float(a[i]), 4), round(float(a[i + 1]), 4)) in ref:
                matched += 1
    f4 = np.frombuffer(b[:len(b) // 4 * 4], '<f4')
    with np.errstate(all='ignore'):
        f4ok = int((np.isfinite(f4) & (f4 > 0.0005) & (f4 < 1.2)).sum())
    rows.append((n, len(b), round(e, 2), z, hits, pairs, matched, f4ok, b[:8].hex()))
    tot['bytes'] += len(b)
    tot['matched'] += matched
rows.sort(key=lambda r: -r[1])
print('streams>=64B', len(rows), dict(tot))
print('name | size | entropy | zlib(off,len) | f8 in-range | f8 pairs | pairs matching PDF endpoints | f4 in-range | head')
for r in rows[:28]:
    print(' | '.join(str(x) for x in r)[:160])
