#!/usr/bin/env python3
"""holes_scan.py DECODE_DIR DIAG_JSON JOB OUT.json
For the pieces still failing in DIAG_JSON ("do not sew"), apply the repair-stage face edits (no OCC) and classify the
remaining defect: 'planar holes only' = no over-used edge and every free-edge loop is a closed planar polygon (a face
the piece file does not store; closing it would add a face, which the owner rule forbids), else 'other'."""
import sys, os, json, collections
import numpy as np
DEC, DJ, job, out = sys.argv[1:5]
sys.path.insert(0, DEC)
import brep


def edge_use(F):
    E = collections.Counter()
    for f in F:
        for l in brep.loops_of(f):
            for a, b in zip(l, l[1:] + l[:1]):
                if a != b:
                    E[(min(a, b), max(a, b))] += 1
    return E


def classify(V, F):
    best = None
    for clean in (True, False):
        brep._CLEAN_LOOPS = clean
        try:
            F2 = brep.conform(V, F)
            F3 = brep.drop_isolated(F2)
            F4 = brep.drop_slivers(V, F3)
            V5, F5 = brep.merge_coplanar(V, F4)
            F6 = brep.conform(V5, F5)
        finally:
            brep._CLEAN_LOOPS = False
        E = edge_use(F6)
        free = [e for e, c in E.items() if c == 1]; over = [e for e, c in E.items() if c > 2]
        adj = collections.defaultdict(list)
        for a, b in free:
            adj[a].append(b); adj[b].append(a)
        loops, seen, ok = [], set(), not over and bool(free)
        for s in adj:
            if s in seen:
                continue
            comp, st = [], [s]
            while st:
                x = st.pop()
                if x in seen: continue
                seen.add(x); comp.append(x); st.extend(adj[x])
            if any(len(adj[x]) != 2 for x in comp):
                ok = False
            P = V5[comp]; c = P.mean(0)
            sv = np.linalg.svd(P - c, compute_uv=False) if len(comp) >= 3 else [0, 0, 1]
            if sv[-1] > 1e-3 * max(1.0, np.sqrt(len(comp))):
                ok = False
            loops.append(len(comp))
        r = dict(free=len(free), over=len(over), holes=len(loops), loop_sizes=sorted(loops)[:8], planar_holes_only=ok)
        if best is None or (r["planar_holes_only"] and not best["planar_holes_only"]) or \
                (r["planar_holes_only"] == best["planar_holes_only"] and r["free"] + r["over"] < best["free"] + best["over"]):
            best = r
    return best


d = json.load(open(DJ))
res = []; tally = collections.Counter(); tally_i = collections.Counter()
for p in d["pieces"]:
    if p.get("why") != "piece faces do not sew into a closed solid":
        continue
    try:
        V, F = brep.parse(open(os.path.join(job, "subm", str(p["sid"])), "rb").read())
        c = classify(np.asarray(V, float), F)
    except Exception as e:
        c = dict(error=f"{type(e).__name__}: {e}", planar_holes_only=False)
    k = "planar holes only" if c.get("planar_holes_only") else ("grating" if p["name"][:2] in ("GT", "GR") else "other")
    tally[k] += 1; tally_i[k] += p.get("n_inst", 0)
    res.append(dict(sid=p["sid"], name=p["name"], n_inst=p.get("n_inst"), cls=k, **c))
json.dump(dict(job=os.path.basename(job), unique=dict(tally), inst=dict(tally_i), pieces=res), open(out, "w"), indent=0)
print(json.dumps(dict(job=os.path.basename(job), unique=dict(tally), inst=dict(tally_i))))
