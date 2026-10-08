"""Look for global placement data in subm/<n> files: search for doubles near given member coordinates,
and dump the tail of the file (placement often stored after the geometry)."""
import os, sys, re, struct
import numpy as np

job = sys.argv[1]
ns = [int(x) for x in sys.argv[2].split(",")]
targets = [float(x) for x in sys.argv[3].split(",")]
np.seterr(all="ignore")
for n in ns:
    b = open(os.path.join(job, "subm", str(n)), "rb").read()
    found = []
    for al in range(8):
        v = np.frombuffer(b[al:al + 8 * ((len(b) - al) // 8)], dtype=">f8")
        for t in targets:
            for i in np.where(np.abs(v - t) < 2.0)[0]:
                found.append((hex(al + 8 * int(i)), round(float(v[i]), 4)))
    print(f"subm/{n} ({len(b)} B): near-target doubles {sorted(set(found))[:20]}")
    # structure guess: count of repeated 8-byte markers
    for al in (0, 2, 4, 6):
        v = np.frombuffer(b[al:al + 8 * ((len(b) - al) // 8)], dtype=">f8")
        big = [(hex(al + 8 * i), round(float(x), 3)) for i, x in enumerate(v) if np.isfinite(x) and 50 < abs(x) < 1e5]
        if big: print(f"   a{al} big values:", big[:16])
