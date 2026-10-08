"""First look at subm/: file sizes, subm_idx slot layout, strings, sample records."""
import os, sys, re, collections, struct
import numpy as np

job = sys.argv[1]
sd = os.path.join(job, "subm")
files = os.listdir(sd)
ids = sorted(int(n) for n in files if n.isdigit())
print("numeric files:", len(ids), "range", ids[0], ids[-1], "; others:", [f for f in files if not f.isdigit()][:10])
sizes = collections.Counter(os.path.getsize(os.path.join(sd, str(n))) for n in ids)
print("sizes top:", sizes.most_common(12), "distinct", len(sizes))
for name in ("subm_ctl", "subm_idx", "subm_list"):
    p = os.path.join(sd, name)
    if not os.path.exists(p): continue
    b = open(p, "rb").read()
    print(f"== {name}: {len(b)} B; per subm {len(b)/len(ids):.2f}")
    if name == "subm_idx":
        pos = [m.start() for m in re.finditer(rb"[A-Za-z][ -~]{3,}", b[:2_000_000])]
        strs = collections.Counter(m.group() for m in re.finditer(rb"[A-Za-z][ -~]{3,}", b[:2_000_000]))
        print("   common strings:", [(s.decode(), c) for s, c in strs.most_common(25)])
        for slot in range(200, 5000):
            if (len(b) - 256) % slot == 0 and 0.9 < (len(b) - 256) / slot / len(ids) < 3:
                print("   candidate slot", slot, "cap", (len(b) - 256) // slot)
np.seterr(all="ignore")
for n in ids[:3] + ids[1000:1002]:
    b = open(os.path.join(sd, str(n)), "rb").read()
    v = np.frombuffer(b[:8 * (min(len(b), 512) // 8)], dtype=">f8")
    print(f"-- subm/{n} ({len(b)} B) doubles@0:", [round(float(x), 3) if np.isfinite(x) and abs(x) < 1e6 else "~" for x in v[:40]])
    print("   strings:", [s.decode() for s in re.findall(rb"[A-Za-z][ -~]{3,}", b)][:15])
