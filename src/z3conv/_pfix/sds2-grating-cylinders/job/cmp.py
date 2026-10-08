#!/usr/bin/env python3
"""cmp.py BASE NEW : per job, manifest before/after (downloaded under ./<ver>/<job>/)."""
import json, os, sys, glob, re
B, N = sys.argv[1], sys.argv[2]
def load(v, j):
    f = glob.glob(f"{v}/{j}/*_stage2_manifest.json")
    if not f: return None
    m = json.load(open(f[0]))
    rc = open(f"{v}/{j}/rc.txt").read().strip() if os.path.exists(f"{v}/{j}/rc.txt") else ""
    m["_rc"] = rc
    return m
def gr(m):
    n = 0
    for g in m["standins"].get("groups", []):
        if re.match(r"(bar grating|G[TR]\d)", g.get("real_type", "")) or "grating" in g.get("type", ""):
            n += g["count"]
    return n
def rods(m):
    return m["standins"]["by_type"].get("mesh_cylinder", 0)
rows = []
for j in sorted(set(os.listdir(B)) & set(os.listdir(N))):
    a, b = load(B, j), load(N, j)
    if not a or not b: continue
    ca, cb = a["counts"], b["counts"]; ra, rb = a["readback"], b["readback"]
    rows.append(dict(job=j, cls=f"{a['class']}{a['corpus']} -> {b['class']}{b['corpus']}",
        mesh_cyl=f"{rods(a)} -> {rods(b)}", grating=f"{gr(a)} -> {gr(b)}",
        exact=f"{ca['pieces_exact']} -> {cb['pieces_exact']}", approx=f"{ca['pieces_approx']} -> {cb['pieces_approx']}",
        skipped=f"{ca['skipped']} -> {cb['skipped']}",
        standins=f"{a['standins']['total']} -> {b['standins']['total']}",
        readback=f"{ra.get('solids')}/{ra.get('valid')} -> {rb.get('solids')}/{rb.get('valid')}",
        steel=f"{a['weight_check'].get('ratio')} -> {b['weight_check'].get('ratio')}",
        g=b.get("grating"), r=b.get("rods"), rc=f"{a['_rc']} | {b['_rc']}",
        reasons=b["class_reasons"]))
json.dump(rows, open(f"cmp_{B}_{N}.json", "w"), indent=1)
for r in rows:
    print(f"{r['job'][:30]:30s} {r['cls']:10s} mesh_cyl {r['mesh_cyl']:14s} grating {r['grating']:12s} exact {r['exact']:16s} approx {r['approx']:12s} skip {r['skipped']:14s} rb {r['readback']:24s} steel {r['steel']}")
