"""Dump the region around a subm-id reference inside mem/<n> to learn the material-instance block layout."""
import os, sys, struct
import numpy as np

job, n, ref_off = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
b = open(os.path.join(job, "mem", str(n)), "rb").read()
lo, hi = max(0, ref_off - 360), min(len(b), ref_off + 320)
np.seterr(all="ignore")
print(f"mem/{n} len {len(b)}; subm id {struct.unpack('>i', b[ref_off:ref_off+4])[0]} at {ref_off}")
for al in range(0, 8, 2):
    start = lo + ((al - lo) % 8)
    v = np.frombuffer(b[start:start + 8 * ((hi - start) // 8)], dtype=">f8")
    good = [(start + 8 * i - ref_off, round(float(x), 4)) for i, x in enumerate(v) if np.isfinite(x) and 1e-3 < abs(x) < 1e5]
    if len(good) >= 3: print(f"  f64 (rel to ref) a{al}:", good)
print("  i32 rel:", [(o - ref_off, struct.unpack('>i', b[o:o+4])[0]) for o in range(lo, hi - 4, 2) if 0 < struct.unpack('>i', b[o:o+4])[0] < 200000][:40])
