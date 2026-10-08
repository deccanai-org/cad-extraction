"""Context of orphan plate refs inside mem/*: which member, offset relative to the 538-B grid, nearby ints/doubles."""
import os, sys, struct, re
import numpy as np
job = sys.argv[1]; ids = [int(x) for x in sys.argv[2].split(",")]
md = os.path.join(job, "mem")
pats = {struct.pack(">i", k): k for k in ids}
rx = re.compile(b"|".join(re.escape(p) for p in pats))
np.seterr(all="ignore")
shown = 0
for f in os.listdir(md):
    if not f.isdigit(): continue
    b = open(os.path.join(md, f), "rb").read()
    n = int(f)
    for m in rx.finditer(b):
        X = m.start()
        ints = [(o - X, struct.unpack(">i", b[o:o + 4])[0]) for o in range(max(0, X - 16), min(len(b) - 4, X + 24), 4)]
        print(f"mem/{n} ({len(b)} B) @{X} piece {pats[m.group()]}  ints {ints}")
        if shown < 3:
            for al in (0, 4):
                lo = X - 0x70 + al
                v = np.frombuffer(b[lo:lo + 8 * 14], dtype=">f8")
                print("    f64 from X-0x70+%d:" % al, [round(float(x), 3) if np.isfinite(x) and abs(x) < 1e6 else None for x in v])
        shown += 1
        if shown > 25: sys.exit()
