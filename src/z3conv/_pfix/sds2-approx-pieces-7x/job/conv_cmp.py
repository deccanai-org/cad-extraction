"""conv_cmp.py OUTDIR BASEVAR CANDVAR: before/after of the stage-2 conversions (log + manifest)."""
import sys, os, re, json, glob
O, B, C = sys.argv[1:4]
APPROX = ("plate_from_vertices", "rolled_profile_extrusion", "piece_table_standin", "vertex_box", "member_envelope")
def info(var, job):
    d = os.path.join(O, var, job); log = os.path.join(d, job + "_stage2.log")
    if not os.path.exists(log): return None
    t = open(log, errors="replace").read()
    r = {}
    m = re.findall(r"manifest after read-back: class (\d) corpus (\w) \(([^)]*)\)", t) or re.findall(r"manifest: class (\d) corpus (\w) \(([^)]*)\)", t)
    if m:
        r["class"] = m[-1][0] + m[-1][1]; r["standins"] = m[-1][2]
        ap = 0
        for n, k in re.findall(r"(\d+) (\w+)", m[-1][2]):
            if k in APPROX: ap += int(n)
        r["approx"] = ap
    m = re.findall(r"with solids: (\d+); BRep valid: (\d+)", t)
    if m: r["solids"], r["valid"] = int(m[-1][0]), int(m[-1][1])
    m = re.findall(r"ratio ([0-9.]+); member envelopes", t)
    if m: r["steel_ratio"] = float(m[-1])
    m = re.findall(r"'exact_brep_repaired': (\d+)", t); r["repaired"] = int(m[-1]) if m else 0
    m = re.findall(r"'exact_brep_weight_unvalidated': (\d+)", t); r["identity"] = int(m[-1]) if m else 0
    m = re.findall(r"'exact_brep_negative_weight': (\d+)", t); r["negwt"] = int(m[-1]) if m else 0
    m = re.findall(r"^version ([0-9.]+)", t, re.M); r["version"] = m[0] if m else "?"
    rc = open(os.path.join(d, "rc.txt")).read().split()[0] if os.path.exists(os.path.join(d, "rc.txt")) else "?"
    r["rc"] = rc
    return r
jobs = sorted(set(os.listdir(os.path.join(O, B))) | set(os.listdir(os.path.join(O, C))))
for j in jobs:
    b, c = info(B, j), info(C, j)
    if not b or not c: print(j, "incomplete", bool(b), bool(c)); continue
    print(f"{c['version']:6} {j[:34]:34} approx {b.get('approx')} -> {c.get('approx')}  class {b.get('class')} -> {c.get('class')}  "
          f"valid {b.get('valid')}/{b.get('solids')} -> {c.get('valid')}/{c.get('solids')}  steel {b.get('steel_ratio')} -> {c.get('steel_ratio')}  "
          f"repaired {c['repaired']} identity {c['identity']} negwt {c['negwt']} rc {b['rc']} {c['rc']}")
