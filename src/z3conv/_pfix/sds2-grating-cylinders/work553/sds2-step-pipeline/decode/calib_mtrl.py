"""Detect job_mtrl record size/base and the section/roll fields for a job; sanity-check with AISC values."""
import os, sys, re, collections, struct
import numpy as np
from calibrate import calibrate

AISC = {"W18x35": (17.7, 6.0, 0.425, 0.3), "W12x19": (12.2, 4.01, 0.35, 0.235), "W14x22": (13.7, 5.0, 0.335, 0.23),
        "W8x31": (8.0, 7.995, 0.435, 0.285), "W10x12": (9.87, 3.96, 0.21, 0.19)}

def mtrl_layout(job):
    b = open(os.path.join(job, "main", "job_mtrl"), "rb").read()
    pos = [m.start() for m in re.finditer(rb"(?<![ -~])(W\d+x[\d.]+|HSS[\dx/.]+|L\d+x[\dx/.]+|C\d+x[\d.]+)\x00", b)]
    sp = collections.Counter(pos[i + 1] - pos[i] for i in range(len(pos) - 1)).most_common(1)[0][0]
    base = collections.Counter(p % sp for p in pos).most_common(1)[0][0]
    # dims offset: find d,bf,tf,tw for a known shape
    dims = None
    for name, vals in AISC.items():
        j = b.find(name.encode() + b"\x00")
        if j < 0: continue
        r = b[j:j + sp]
        key = struct.pack(">2d", vals[0], vals[1])
        k = r.find(key)
        if k >= 0: dims = k; break
    names = []
    for k in range((len(b) - base) // sp):
        m = re.match(rb"[ -~]+", b[base + k * sp: base + k * sp + 40]); names.append(m.group().decode() if m else "")
    return sp, base, dims, names

for job in sys.argv[1:]:
    c = calibrate(job, verbose=False)
    sp, base, dims, names = mtrl_layout(job)
    print(f"== {os.path.basename(job)}: mtrl rec={sp} base={base:#x} dims@+{dims if dims is None else hex(dims)} n={len(names)} first={names[:3]}")
    idx = open(os.path.join(job, "mem", "mem_idx"), "rb").read()
    # try section offsets near p2 and see which gives W shapes for BEAM
    for so in range(c["p2"] + 0x40, c["p2"] + 0x90, 2):
        cnt = collections.Counter(); tot = 0
        for n in range(1, c["n_members"] + 1):
            s = idx[n * c["slot"]:(n + 1) * c["slot"]]
            if len(s) < c["slot"]: continue
            t = re.match(rb"[ -~]*", s[c["type"]:c["type"] + 20]).group().decode()
            if t != "BEAM": continue
            v = struct.unpack(">h", s[so:so + 2])[0]
            tot += 1
            if 1 <= v <= len(names): cnt[re.match(r"[A-Z]*", names[v - 1]).group()] += 1
        if tot and cnt.get("W", 0) > 0.6 * tot:
            print(f"   section field candidate {so:#x}: beams->family {cnt.most_common(3)} of {tot}")
