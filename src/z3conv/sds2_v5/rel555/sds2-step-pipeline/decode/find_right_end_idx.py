"""Search each mem_idx slot (2494 B) for the member's second work point, using P1 from mem/<n> @0x48."""
import os, sys, collections, re
import numpy as np

job = sys.argv[1]
SLOT = 2494
md = os.path.join(job, "mem")
idx = open(os.path.join(md, "mem_idx"), "rb").read()
np.seterr(all="ignore")
hist = collections.defaultdict(collections.Counter); nrec = collections.Counter()
for n in os.listdir(md):
    if not n.isdigit(): continue
    k = int(n)
    s = idx[k * SLOT:(k + 1) * SLOT]
    m = re.match(rb"[ -~]+", s[0x988:0x988 + 24]); t = m.group().decode() if m else "?"
    if t not in ("BEAM", "COLUMN", "VERTICAL BRACE", "MISC"): continue
    b = open(os.path.join(md, n), "rb").read(0x60)
    if len(b) < 0x60: continue
    p1 = np.frombuffer(b[0x48:0x60], dtype=">f8").astype(float)
    nrec[t] += 1
    seen = set()
    for al in range(8):
        mm = (len(s) - al) // 8
        v = np.frombuffer(s[al:al + 8 * mm], dtype=">f8").astype(float)
        T = np.c_[v[:-2], v[1:-1], v[2:]]
        offs = al + 8 * np.arange(len(T))
        fin = np.isfinite(T).all(1) & (np.abs(T) < 1e5).all(1)
        d = np.linalg.norm(T - p1, axis=1)
        if t == "COLUMN":
            ok = (np.linalg.norm(T[:, :2] - p1[:2], axis=1) < 0.01) & (np.abs(T[:, 2] - p1[2]) > 24)
        elif t == "BEAM":
            ok = (np.abs(T[:, 2] - p1[2]) < 0.01) & (d > 24) & (d < 3000) & ((np.abs(T[:, :2]) > 1).all(1))
        else:
            ok = (d > 24) & (d < 5000) & ((np.abs(T) > 1).sum(1) >= 2)
        for o in offs[fin & ok]:
            if int(o) not in seen:
                seen.add(int(o)); hist[t][int(o)] += 1
    # where is P1 itself in the slot
    for al in range(8):
        pass
for t in hist:
    print(f"{t}: {nrec[t]} slots; top offsets:", [(hex(o), c) for o, c in hist[t].most_common(8)])
