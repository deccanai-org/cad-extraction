"""Find f64 BE values (within tol) in files; report file, offset, and neighbouring doubles.
usage: python find_value.py <tol> <v1,v2,...> <file-or-dir> [...]"""
import os, sys, struct
import numpy as np
tol = float(sys.argv[1]); vals = [float(x) for x in sys.argv[2].split(",")]
paths = []
for p in sys.argv[3:]:
    if os.path.isdir(p):
        paths += [os.path.join(p, f) for f in os.listdir(p)]
    else:
        paths.append(p)
np.seterr(all="ignore")
for p in paths:
    try: b = open(p, "rb").read()
    except OSError: continue
    for al in range(8):
        v = np.frombuffer(b[al:al + 8 * ((len(b) - al) // 8)], dtype=">f8")
        for t in vals:
            for i in np.where(np.abs(v - t) < tol)[0][:5]:
                ctx = [round(float(x), 3) if np.isfinite(x) and abs(x) < 1e6 else None for x in v[max(0, i - 6):i + 7]]
                print(f"{os.path.relpath(p)} @{al + 8 * int(i):#x} val={v[i]:.4f} ctx={ctx}")
