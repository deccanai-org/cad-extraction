"""agg2.py BEFORE_TAGS AFTER_TAGS: per-version table of placed plate / rolled / BLT pieces whose exact B-rep is
rejected (they go to the approximate builders). before = base553 diag; after = the latest candidate per job
(cand9 over cand8). Remaining placements are split: grating (GR/GT, other item), piece file without faces, rest."""
import json, glob, collections, sys
def load(tags, prefs):
    out = {}
    for t in tags:
        for f in glob.glob(f"{t}/*.json"):
            if f.endswith("_dump.json"): continue
            var = f.split("/")[-1].split("__")[0]
            if var not in prefs: continue
            d = json.load(open(f)); j = d["summary"]["job"]
            if j not in out or prefs.index(var) < prefs.index(out[j][0]):
                out[j] = (var, d)
    return out
def split(d):
    c = collections.Counter()
    for p in d["pieces"]:
        n = p.get("n_inst", 0); w = p.get("why") or ""
        if p["name"][:2] in ("GR", "GT"): c["grating"] += n
        elif "readable" in w or "missing" in w: c["no_faces"] += n
        else: c["rest"] += n
    return c
B = load(sys.argv[1].split(","), ["base553"]); A = load(sys.argv[2].split(","), ["cand9", "cand8"])
V = collections.defaultdict(collections.Counter); rows = []
for j in sorted(set(B) & set(A)):
    b, a = B[j][1], A[j][1]; ver = b["summary"]["version"]
    sb, sa = split(b), split(a)
    rows.append(dict(job=j, version=ver, after_variant=A[j][0], placed=b["summary"]["inst_ok"] + b["summary"]["inst_bad"],
                     approx_before=b["summary"]["inst_bad"], approx_after=a["summary"]["inst_bad"],
                     unique_before=b["summary"]["unique_bad"], unique_after=a["summary"]["unique_bad"],
                     exact_before=b["summary"]["inst_ok"], exact_after=a["summary"]["inst_ok"],
                     before_split=dict(sb), after_split=dict(sa), why_after=a["summary"]["why_inst"],
                     repaired=a["summary"].get("inst_repaired", 0), identity=a["summary"].get("inst_weight_notes", 0)))
    c = V[ver[:3]]; c["jobs"] += 1; c["placed"] += rows[-1]["placed"]
    c["approx_before"] += rows[-1]["approx_before"]; c["approx_after"] += rows[-1]["approx_after"]
    for k in ("grating", "no_faces", "rest"):
        c[k + "_before"] += sb[k]; c[k + "_after"] += sa[k]
    c["exact_lost"] += max(0, rows[-1]["exact_before"] - rows[-1]["exact_after"])
json.dump(dict(rows=rows, by_version={k: dict(v) for k, v in V.items()}), open("data_versions.json", "w"), indent=1)
for r in rows: print(f"{r['version']:6} {r['job'][:36]:36} {r['approx_before']:5} -> {r['approx_after']:5}  rest {r['before_split'].get('rest',0)} -> {r['after_split'].get('rest',0)}  ({r['after_variant']}) exact {r['exact_before']} -> {r['exact_after']}")
print()
print("ver jobs placed | approx before -> after | of which: grating b->a, no-faces b->a, rest b->a | exact lost")
T = collections.Counter()
for v in sorted(V):
    c = V[v]; T.update(c)
for v in sorted(V) + ["all"]:
    c = V[v] if v != "all" else T
    print(f"{v:4} {c['jobs']:3} {c['placed']:7} | {c['approx_before']:5} -> {c['approx_after']:5} | {c['grating_before']}->{c['grating_after']}, {c['no_faces_before']}->{c['no_faces_after']}, {c['rest_before']}->{c['rest_after']} | {c['exact_lost']}")
print("unpaired:", sorted(set(B) ^ set(A)))
