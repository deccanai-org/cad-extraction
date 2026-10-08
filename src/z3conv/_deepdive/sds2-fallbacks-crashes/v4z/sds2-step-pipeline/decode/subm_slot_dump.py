"""Dump subm_idx 852-byte slots: strings, doubles (all 4 even alignments), small ints that could be member ids."""
import os, sys, re, struct
import numpy as np

job = sys.argv[1]
SLOT = int(sys.argv[2]) if len(sys.argv) > 2 else 852
ns = [int(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else [1, 3, 1001, 1002]
b = open(os.path.join(job, "subm", "subm_idx"), "rb").read()
np.seterr(all="ignore")
for n in ns:
    s = b[n * SLOT:(n + 1) * SLOT]
    print(f"===== subm {n}: strings", [(hex(m.start()), m.group().decode()) for m in re.finditer(rb"[A-Za-z0-9#][ -~]{2,}", s)])
    for al in (0, 2, 4, 6):
        v = np.frombuffer(s[al:al + 8 * ((SLOT - al) // 8)], dtype=">f8")
        good = [(hex(al + 8 * i), round(float(x), 4)) for i, x in enumerate(v) if np.isfinite(x) and 1e-3 < abs(x) < 1e6]
        if len(good) >= 3: print(f"  f64 align{al}:", good)
    ints = [(hex(o), struct.unpack(">i", s[o:o + 4])[0]) for o in range(0, SLOT - 4, 2)]
    print("  i32 in 1..9100:", [(o, v) for o, v in ints if 1 <= v <= 9100][:30])
