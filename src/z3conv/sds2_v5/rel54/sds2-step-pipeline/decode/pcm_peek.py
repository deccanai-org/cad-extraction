"""First look at pcm/ and subm_list: names, sizes, strings, whether they reference subm ids / hold transforms."""
import os, sys, re, collections, struct
import numpy as np

job = sys.argv[1]
pd = os.path.join(job, "pcm")
fs = os.listdir(pd)
print("pcm files:", len(fs), "sample names:", sorted(fs)[:8], sorted(fs)[-5:])
sz = collections.Counter(os.path.getsize(os.path.join(pd, f)) // 1000 for f in fs)
print("size (KB) top:", sz.most_common(8))
np.seterr(all="ignore")
for f in sorted(fs, key=lambda x: (len(x), x))[:3]:
    b = open(os.path.join(pd, f), "rb").read()
    print(f"== pcm/{f} {len(b)} B head:", b[:64].hex())
    print("   strings:", [s.decode() for s in re.findall(rb"[A-Za-z0-9][ -~]{3,}", b[:20000])][:30])
    v = np.frombuffer(b[:8 * (min(len(b), 4000) // 8)], dtype=">f8")
    print("   f64 a0 big:", [(hex(8 * i), round(float(x), 3)) for i, x in enumerate(v) if np.isfinite(x) and 20 < abs(x) < 1e5][:20])
sl = open(os.path.join(job, "subm", "subm_list"), "rb").read()
print("subm_list head:", sl[:256].hex())
print("subm_list as >i (from 256):", struct.unpack(">48i", sl[256:256 + 192]))
