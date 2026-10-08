"""Dump job_mtrl records (510 B, name at record start) as doubles at alignments 0/2/4/6, for a few known shapes."""
import os, sys, re, struct
import numpy as np
job = sys.argv[1]
jm = open(os.path.join(job, "main", "job_mtrl"), "rb").read()
REC, BASE = 510, 0x2fe
n = (len(jm) - BASE) // REC
print("records:", n, "tail rem", (len(jm) - BASE) % REC)
names = []
for k in range(n):
    r = jm[BASE + k * REC: BASE + (k + 1) * REC]
    m = re.match(rb"[ -~]+", r); names.append(m.group().decode() if m else "")
print("first names:", names[:5], "... kinds:", sorted({re.match(r"[A-Z]+", x).group() for x in names if re.match(r"[A-Z]+", x)}))
np.seterr(all="ignore")
for want in ("W18x35", "W14x455", "HSS4x4x1/4", "L4x4x3/8", "C8x11.5"):
    k = names.index(want)
    r = jm[BASE + k * REC: BASE + (k + 1) * REC]
    print("==", want, "rec", k)
    for al in (0, 2, 4, 6):
        v = np.frombuffer(r[al:al + 8 * ((REC - al) // 8)], dtype=">f8")
        good = [(hex(al + 8 * i), round(float(x), 4)) for i, x in enumerate(v) if np.isfinite(x) and 0.01 < abs(x) < 1e4]
        if len(good) > 3: print("  align", al, good[:24])
