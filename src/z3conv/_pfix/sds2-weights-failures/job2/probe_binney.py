import os, sys, re, struct, collections, numpy as np
job = sys.argv[1]
sys.path.insert(0, sys.argv[2])
import sds2job
md = os.path.join(job, "mem"); idx = open(os.path.join(md, "mem_idx"), "rb").read()
ids = sorted(int(n) for n in os.listdir(md) if n.isdigit())
print("version", sds2job.read_version(job), "mem_idx", len(idx), "members", len(ids), "max id", max(ids) if ids else None)
sizes = collections.Counter(os.path.getsize(os.path.join(md, str(n))) for n in ids)
print("member file sizes", sizes.most_common(8))
pos = [m.start() for m in re.finditer(rb"(?<![ -~])(BEAM|COLUMN|VERTICAL BRACE|HORIZONTAL BRACE|MISC|STAIR|JOIST|Wall|Ref Point|EMBED)\x00", idx)]
types = collections.Counter(re.match(rb"[ -~]+", idx[p:p+30]).group().decode() for p in pos)
print("type markers", types.most_common(10))
slotc = collections.Counter(pos[i + 1] - pos[i] for i in range(len(pos) - 1)).most_common(5)
print("slot candidates", slotc)
for s in (1280, 1416, 2494, 2944, 2976, 3204, 3404, 3600):
    if (len(idx) - 256) % s == 0: print("divides", s, (len(idx) - 256) // s)
slot = slotc[0][0] if slotc else 2494
print("type offsets", collections.Counter(p % slot for p in pos).most_common(4))
nz = 0
for n in ids[:400]:
    k = open(os.path.join(md, str(n)), "rb").read(0x60)[0x48:0x60]
    if len(k) == 24 and any(k): nz += 1
print("member files with non-zero work point (first 400):", nz)
for n in ids[:5]:
    b = open(os.path.join(md, str(n)), "rb").read(0x60)
    print(n, b[0x48:0x60].hex(), struct.unpack(">3d", b[0x48:0x60]) if len(b) >= 0x60 else None)
shapes = sds2job.read_shapes(job); print("shapes", len(shapes))
try:
    L = sds2job.sparse_layout(job, shapes); print("sparse", L)
except Exception as e:
    print("sparse err", e)
# fixed 2494 7.245 layout typed count
for so in (0x988,):
    t = collections.Counter(sds2job._ascii(idx[n*2494+so:n*2494+so+32]) for n in ids)
    print("2494 @0x988 types", t.most_common(6))
