"""Print mem_idx slot doubles 0x100..0x240 (alignment 2) for a few members of each type."""
import os, sys, re, struct
import numpy as np
job = sys.argv[1]
SLOT = 2494
md = os.path.join(job, "mem")
idx = open(os.path.join(md, "mem_idx"), "rb").read()
shown = {}
np.seterr(all="ignore")
for n in range(1, 9091):
    s = idx[n * SLOT:(n + 1) * SLOT]
    m = re.match(rb"[ -~]+", s[0x988:0x9a0]); t = m.group().decode() if m else "?"
    if t not in ("BEAM", "COLUMN", "VERTICAL BRACE") or shown.get(t, 0) >= 3: continue
    shown[t] = shown.get(t, 0) + 1
    v = np.frombuffer(s[0x102:0x102 + 8 * 40], dtype=">f8")
    print(f"== {n} {t} sec#{struct.unpack('>h', s[0x1d4:0x1d6])[0]}")
    for i in range(0, 40, 3):
        print(f"  {0x102 + 8*i:#05x}: " + "  ".join(f"{x:10.4f}" if np.isfinite(x) and abs(x) < 1e6 else "     ~    " for x in v[i:i+3]))
