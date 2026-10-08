#!/usr/bin/env python3
"""marker_match.py DECODE_DIR JOB HOLES_JSON -> for 'planar holes only' pieces: does a kind-7 (marker) face record of the
piece file cover a hole loop (same vertex coordinates)? Layout 0 (7.1xx-8.0xx) records only."""
import sys, os, json, struct, collections
import numpy as np
DEC, job, hj = sys.argv[1:4]
sys.path.insert(0, DEC)
import brep
d = json.load(open(hj)); out = collections.Counter(); ex = []
for p in d["pieces"]:
    if p.get("cls") != "planar holes only":
        continue
    b = open(os.path.join(job, "subm", str(p["sid"])), "rb").read()
    hdr = 0x1C
    nv, nf, ne = struct.unpack(">3I", b[hdr:hdr + 12])
    v0 = hdr + 16; l0 = v0 + 28 * nv; f0 = l0 + 10 * ne
    if f0 + 22 * nf > len(b):
        out["not layout 0"] += 1; continue
    V = np.array([struct.unpack(">3d", b[v0 + 28 * i:v0 + 28 * i + 24]) for i in range(nv)])
    lo = [struct.unpack(">I", b[l0 + 10 * k:l0 + 10 * k + 4])[0] for k in range(ne)]
    k = 0; markers = []
    for i in range(nf):
        c = struct.unpack(">H", b[f0 + 22 * i + 2:f0 + 22 * i + 4])[0]; kd = b[f0 + 22 * i + 4]
        if kd == 7 and c >= 3:
            markers.append(lo[k:k + c])
        k += c
    r = brep.parse(b)
    if r is None:
        out["no parse"] += 1; continue
    Vp, F = r
    E = collections.Counter()
    for f in brep.conform(Vp, F):
        for l in brep.loops_of(f):
            for a, c in zip(l, l[1:] + l[:1]):
                if a != c: E[(min(a, c), max(a, c))] += 1
    hole_pts = np.array([Vp[i] for e, n in E.items() if n == 1 for i in e])
    hit = False
    for m in markers:
        P = V[m]
        if len(hole_pts) and all(np.min(np.linalg.norm(hole_pts - q, axis=1)) < 1e-3 for q in P):
            hit = True; break
    out["marker covers hole" if hit else "no marker on hole"] += p.get("n_inst") or 0
    if hit and len(ex) < 10:
        ex.append((p["sid"], p["name"]))
print(json.dumps(dict(job=os.path.basename(job), inst=dict(out), examples=ex)))
