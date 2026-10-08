"""Find the field that encodes the cross-section, using IFC-matched pairs (mem_ifc_pairs.csv).

For every 2/4-byte int and every short ASCII window in mem/<n> header and the mem_idx slot, measure how well the
value predicts the IFC section (purity) and how many distinct values it has.
"""
import os, sys, csv, collections, struct, re

job, pairs_csv = sys.argv[1], sys.argv[2]
SLOT = 2494
md = os.path.join(job, "mem")
idx = open(os.path.join(md, "mem_idx"), "rb").read()
pairs = {}
for r in csv.DictReader(open(pairs_csv)):
    pairs[int(r["mem_id"])] = r["section"]
secs = collections.Counter(pairs.values())
print("pairs", len(pairs), "distinct sections", len(secs))

def score(getter, span, label):
    out = []
    for off in range(0, span):
        m = collections.defaultdict(collections.Counter)
        for n, sec in pairs.items():
            v = getter(n, off)
            if v is None: continue
            m[v][sec] += 1
        if len(m) < 5: continue
        tot = sum(sum(c.values()) for c in m.values())
        pure = sum(c.most_common(1)[0][1] for c in m.values()) / tot
        # reverse purity: section -> value
        rv = collections.defaultdict(collections.Counter)
        for v, c in m.items():
            for s, k in c.items(): rv[s][v] += k
        rpure = sum(c.most_common(1)[0][1] for c in rv.values()) / tot
        out.append((pure * rpure, pure, rpure, off, len(m)))
    out.sort(reverse=True)
    print(label, [(hex(o), round(p, 3), round(rp, 3), nv) for _, p, rp, o, nv in out[:8]])

mems = {n: open(os.path.join(md, str(n)), "rb").read(0x400) for n in pairs}
def g_mem_i32(n, off):
    b = mems[n]; return struct.unpack(">i", b[off:off + 4])[0] if off + 4 <= len(b) else None
def g_mem_i16(n, off):
    b = mems[n]; return struct.unpack(">h", b[off:off + 2])[0] if off + 2 <= len(b) else None
def g_idx_i32(n, off):
    return struct.unpack(">i", idx[n * SLOT + off:n * SLOT + off + 4])[0]
score(g_mem_i32, 0x3fc, "mem int32:")
score(g_mem_i16, 0x3fe, "mem int16:")
score(g_idx_i32, SLOT - 4, "idx int32:")
# ASCII in idx slots near member type
ex = list(pairs.items())[:3]
for n, sec in ex:
    s = idx[n * SLOT:(n + 1) * SLOT]
    print(n, sec, [(hex(m.start()), m.group().decode()) for m in re.finditer(rb"[ -~]{3,}", s)])
