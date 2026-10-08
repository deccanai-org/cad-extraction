"""For BEAM/COLUMN/BRACE/MISC records, find which byte offset holds the second work point (vectorised).

BEAM: aligned double triple with z == P1.z and 24 < |q-P1| < 3000 in.
COLUMN: same x,y as P1, 24 < |dz| < 3000.
others: 24 < |q-P1| < 5000, plausible magnitudes.
"""
import os, sys, collections, re
import numpy as np

job = sys.argv[1]
SLOT = 2494
md = os.path.join(job, "mem")
idx = open(os.path.join(md, "mem_idx"), "rb").read()
def mtype(n):
    m = re.match(rb"[ -~]+", idx[n * SLOT + 0x988: n * SLOT + 0x988 + 24]); return m.group().decode() if m else "?"
hist = collections.defaultdict(collections.Counter); nrec = collections.Counter()
np.seterr(all="ignore")
for n in os.listdir(md):
    if not n.isdigit(): continue
    t = mtype(int(n))
    if t not in ("BEAM", "COLUMN", "VERTICAL BRACE", "MISC", "PL GIRDER"): continue
    b = open(os.path.join(md, n), "rb").read()
    if len(b) < 0xE8: continue
    nrec[t] += 1
    p1 = np.frombuffer(b[0x48:0x60], dtype=">f8").astype(float)
    seen = set()
    for al in (0, 2, 4, 6):
        m = (len(b) - al) // 8
        v = np.frombuffer(b[al:al + 8 * m], dtype=">f8").astype(float)
        if len(v) < 3: continue
        T = np.c_[v[:-2], v[1:-1], v[2:]]
        offs = al + 8 * np.arange(len(T))
        fin = np.isfinite(T).all(1) & (np.abs(T) < 1e5).all(1) & (np.abs(offs - 0x48) > 16)
        d = np.linalg.norm(T - p1, axis=1)
        if t == "COLUMN":
            ok = (np.linalg.norm(T[:, :2] - p1[:2], axis=1) < 0.01) & (np.abs(T[:, 2] - p1[2]) > 24) & (np.abs(T[:, 2] - p1[2]) < 3000)
        elif t == "BEAM":
            ok = (np.abs(T[:, 2] - p1[2]) < 0.01) & (d > 24) & (d < 3000) & ((np.abs(T[:, :2]) > 1).all(1))
        else:
            ok = (d > 24) & (d < 5000) & ((np.abs(T) > 1).sum(1) >= 2)
        for o in offs[fin & ok]:
            if o not in seen:
                seen.add(o); hist[t][int(o)] += 1
for t in hist:
    print(f"{t}: {nrec[t]} records; top offsets:", [(hex(o), c) for o, c in hist[t].most_common(10)])
