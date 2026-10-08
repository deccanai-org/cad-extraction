"""For one member: list (piece id, member id) pairs that are plates, with doubles before/after to find the layout."""
import os, sys, struct, re, csv
import numpy as np
from piece_table import read_pieces, kind

job, pairs_csv, pm = sys.argv[1], sys.argv[2], sys.argv[3]
n = next(int(r["mem_id"]) for r in csv.DictReader(open(pairs_csv)) if r["piecemark"] == pm)
P = read_pieces(job)
b = open(os.path.join(job, "mem", str(n)), "rb").read()
print(f"{pm} = mem {n}, {len(b)} B")
tag = struct.pack(">i", n)
np.seterr(all="ignore")
xs = []
for m in re.finditer(re.escape(tag), b):
    X = m.start() - 4
    p = P.get(struct.unpack(">i", b[X:X + 4])[0]) if X >= 0 else None
    if p and kind(p) == "plate": xs.append((X, p["name"], round(p["L"], 3), round(p["W"], 3), round(p["T"], 3)))
print("plate refs:", len(xs), "gaps:", [xs[i + 1][0] - xs[i][0] for i in range(min(len(xs) - 1, 30))])
for X, *info in xs[:3]:
    print(f"--- X={X} {info}")
    for al in range(0, 8, 2):
        lo = X - 400 + ((al - (X - 400)) % 8)
        v = np.frombuffer(b[lo:lo + 8 * 100], dtype=">f8")
        good = [(lo + 8 * i - X, round(float(x), 3)) for i, x in enumerate(v) if np.isfinite(x) and 1e-3 < abs(x) < 1e5]
        if len(good) > 3: print(f"   a{al}:", good)
    print("   i32:", [(o - X, struct.unpack('>i', b[o:o + 4])[0]) for o in range(X - 120, X + 60, 2) if 0 < struct.unpack('>i', b[o:o + 4])[0] < 100000])
