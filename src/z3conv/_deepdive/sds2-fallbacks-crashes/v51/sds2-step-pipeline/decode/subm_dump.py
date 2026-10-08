"""Hex + f64 dump of a subm/<n> file in 8-byte rows at a chosen alignment, with i32 view, to read its structure."""
import os, sys, struct
import numpy as np

job, n = sys.argv[1], int(sys.argv[2])
al = int(sys.argv[3]) if len(sys.argv) > 3 else 0
lim = int(sys.argv[4]) if len(sys.argv) > 4 else 2000
b = open(os.path.join(job, "subm", str(n)), "rb").read()
print(f"subm/{n}: {len(b)} B, alignment {al}")
np.seterr(all="ignore")
for o in range(al, min(len(b), lim) - 7, 8):
    w = b[o:o + 8]
    d = struct.unpack(">d", w)[0]
    i1, i2 = struct.unpack(">ii", w)
    ds = f"{d:12.4f}" if np.isfinite(d) and (d == 0 or 1e-4 < abs(d) < 1e6) else "     .      "
    print(f"{o:05x} {w.hex()}  f64={ds}  i32=({i1},{i2})")
