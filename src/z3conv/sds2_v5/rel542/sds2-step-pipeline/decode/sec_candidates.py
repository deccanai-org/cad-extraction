"""Show section names chosen by candidate section-field offsets, per member type; and roll-field candidates."""
import os, sys, re, collections, struct
import numpy as np
from calibrate import calibrate

job = sys.argv[1]
offs = [int(x, 16) for x in sys.argv[2].split(",")]
c = calibrate(job, verbose=False)
b = open(os.path.join(job, "main", "job_mtrl"), "rb").read()
names = {}
for k in range((len(b) - 0x2FE) // 510):
    m = re.match(rb"[ -~]+", b[0x2FE + k * 510:0x2FE + k * 510 + 40]); names[k + 1] = m.group().decode() if m else ""
idx = open(os.path.join(job, "mem", "mem_idx"), "rb").read()
for so in offs:
    print(f"== section field {so:#x}")
    for want in ("BEAM", "COLUMN", "VERTICAL BRACE"):
        cnt = collections.Counter()
        for n in range(1, c["n_members"] + 1):
            s = idx[n * c["slot"]:(n + 1) * c["slot"]]
            if len(s) < c["slot"]: continue
            if re.match(rb"[ -~]*", s[c["type"]:c["type"] + 20]).group().decode() != want: continue
            cnt[names.get(struct.unpack(">h", s[so:so + 2])[0], "?")] += 1
        print(f"   {want}: {cnt.most_common(6)}")
np.seterr(all="ignore")
print("== roll candidates (f64 where columns show +-pi/2)")
for ro in range(c["p2"] + 0x18, c["p2"] + 0xA0, 2):
    vals = []
    for n in range(1, c["n_members"] + 1):
        s = idx[n * c["slot"]:(n + 1) * c["slot"]]
        if len(s) < c["slot"]: continue
        if re.match(rb"[ -~]*", s[c["type"]:c["type"] + 20]).group().decode() != "COLUMN": continue
        vals.append(struct.unpack(">d", s[ro:ro + 8])[0])
    v = np.array(vals)
    if len(v) and np.mean(np.isclose(np.abs(v), np.pi / 2, atol=1e-3) | np.isclose(v, 0)) > 0.9 and np.mean(np.isclose(np.abs(v), np.pi / 2, atol=1e-3)) > 0.1:
        print(f"   {ro:#x}: share pi/2 {np.mean(np.isclose(np.abs(v), np.pi/2, atol=1e-3)):.2f}")
