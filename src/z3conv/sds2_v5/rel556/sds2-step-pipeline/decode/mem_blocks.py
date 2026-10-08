"""Split a mem/<n> record into header + blocks (blocks carry the member id at +112) and dump each block."""
import os, sys, re, struct
import numpy as np

job, n = sys.argv[1], int(sys.argv[2])
b = open(os.path.join(job, "mem", str(n)), "rb").read()
tag = struct.pack(">i", n)
starts = [m.start() - 112 for m in re.finditer(re.escape(tag), b) if m.start() >= 112 + 0x200]
# keep starts consistent with block grid: a start is valid if the next tag is at a common block length
starts = sorted(set(s for s in starts if s >= 0x200))
print(f"mem/{n}: {len(b)} B; tag-derived block starts:", [hex(s) for s in starts][:40])
d = [starts[i + 1] - starts[i] for i in range(len(starts) - 1)]
print("gaps:", d[:40])
np.seterr(all="ignore")
for s in starts[:6]:
    blk = b[s:s + 700]
    print(f"--- block @{s:#x}")
    for al in (0, 2, 4, 6):
        v = np.frombuffer(blk[al:al + 8 * ((len(blk) - al) // 8)], dtype=">f8")
        good = [(hex(al + 8 * i), round(float(x), 4)) for i, x in enumerate(v) if np.isfinite(x) and 1e-3 < abs(x) < 1e6]
        if len(good) >= 4: print(f"  f64 a{al}:", good[:30])
    print("  strings:", [(hex(m.start()), m.group().decode()) for m in re.finditer(rb"[A-Za-z][ -~]{2,}", blk)][:6])
    print("  i32 small:", [(hex(o), struct.unpack('>i', blk[o:o+4])[0]) for o in range(0, 200, 2) if 0 < struct.unpack('>i', blk[o:o+4])[0] < 100000][:16])
