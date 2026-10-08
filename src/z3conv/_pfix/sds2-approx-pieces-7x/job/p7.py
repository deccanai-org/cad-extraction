"""p7.py JOB SID: raw face records of a piece file (layout 0): count, kind, the 22 record bytes, and which records
touch the free-edge loop vertices left after the repair edits (are the missing faces anywhere in the file?)."""
import sys, os, struct, collections
import numpy as np
DEC, job, sid = sys.argv[1], sys.argv[2], int(sys.argv[3])
sys.path.insert(0, DEC)
import brep
b = open(os.path.join(job, "subm", str(sid)), "rb").read()
hdr = 0x1C; nv, nf, ne = struct.unpack(">3I", b[hdr:hdr + 12])
v0 = hdr + 16; l0 = v0 + 28 * nv; f0 = l0 + 10 * ne
V = np.array([struct.unpack(">3d", b[v0 + 28 * i:v0 + 28 * i + 24]) for i in range(nv)])
tags = [b[v0 + 28 * i + 24] for i in range(nv)]
lo = [struct.unpack(">I", b[l0 + 10 * k:l0 + 10 * k + 4])[0] for k in range(ne)]
lflags = [b[l0 + 10 * k + 4:l0 + 10 * k + 10].hex() for k in range(ne)]
r = brep.parse(b); Vp, F = r
brep._CLEAN_LOOPS = True
F2 = brep.conform(Vp, F)
E = collections.Counter()
for f in F2:
    for l in brep.loops_of(f):
        for a, c in zip(l, l[1:] + l[:1]):
            if a != c: E[(min(a, c), max(a, c))] += 1
brep._CLEAN_LOOPS = False
free = {i for e, n in E.items() if n == 1 for i in e}
print("nv", nv, "nf", nf, "ne", ne, "free-loop vertices", sorted(free), "file len", len(b), "after faces", len(b) - (f0 + 22 * nf))
k = 0
for i in range(nf):
    rec = b[f0 + 22 * i:f0 + 22 * i + 22]
    c = struct.unpack(">H", rec[2:4])[0]; kd = rec[4]
    ent = lo[k:k + c]; k += c
    hit = len(set(ent) & free)
    print(i, "count", c, "kind", kd, "rec", rec.hex(), "entries", ent, "hits", hit)
print("vertex tags", collections.Counter(tags))
print("free vertex coords", [(i, tuple(np.round(V[i], 4)), tags[i]) for i in sorted(free)])
