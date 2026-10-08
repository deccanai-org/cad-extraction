"""Read-only: characterise G5 mismatches (STEP solid bbox vs independently rebuilt piece bbox)."""
import sys, json, collections
import numpy as np
from piece_table import read_pieces, kind

job, step = sys.argv[1], sys.argv[2]
T = json.load(open(step + ".table.json"))["solids"]
E = {tuple(map(int, k.split(":"))): v for k, v in json.load(open(step + ".expected.json")).items()}
pieces = read_pieces(job)
bad = collections.Counter(); tot = collections.Counter(); ex = collections.defaultdict(list)
for t in T:
    c = E.get((t["member_id"], t["piece_id"]))
    if not c: continue
    k = kind(pieces[t["piece_id"]]); fam = "".join(ch for ch in (t["section"] or "") if ch.isalpha())[:4]
    lo, hi = np.array(t["lo"]), np.array(t["hi"])
    best = min(c, key=lambda b: max(np.abs(lo - b[0]).max(), np.abs(hi - b[1]).max()))
    d = np.r_[lo - best[0], hi - best[1]]
    e = np.abs(d).max()
    tot[(k, fam)] += 1
    if e > 0.1:
        bad[(k, fam)] += 1
        if len(ex[(k, fam)]) < 2:
            ex[(k, fam)].append(dict(name=t["name"], err=round(float(e), 2), step_ext=np.round(hi - lo, 2).tolist(),
                                     exp_ext=np.round(np.array(best[1]) - best[0], 2).tolist(), d=np.round(d, 2).tolist(), n_cands=len(c)))
for key, n in sorted(tot.items(), key=lambda kv: -kv[1])[:12]:
    print(f"{key}: {bad[key]}/{n} mismatched")
    for e in ex[key]: print("    ", e)
