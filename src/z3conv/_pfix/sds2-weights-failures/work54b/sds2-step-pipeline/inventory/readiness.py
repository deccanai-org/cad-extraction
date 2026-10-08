"""Group candidate models by decoder readiness and flag archives that already carry IFC/STEP exports.
usage: python readiness.py disk2_archives.jsonl disk2_models.csv"""
import sys, json, csv, collections, re

recs = {}
for line in open(sys.argv[1], encoding="utf-8"):
    r = json.loads(line)
    if r["key"] not in recs or "error" in recs[r["key"]]:
        recs[r["key"]] = r
arch_fmt = {k[len("Disk-2/"):]: r.get("formats", {}) for k, r in recs.items()}
rows = list(csv.DictReader(open(sys.argv[2], encoding="utf-8")))
uniq = {}
for j in rows:
    if j["ifc_done"] == "True" or j["junk"] == "True": continue
    k = j["name"]
    if k not in uniq or int(j["members"]) > int(uniq[k]["members"]): uniq[k] = j

def tier(v):
    if not v: return "E unknown version"
    if v.startswith("7.2"): return "A 7.2xx - members + pieces decoded (validated)"
    if v.startswith("7.3"): return "B 7.3xx - members decoded, pieces need offset check"
    if v.startswith("7.1") or v.startswith("7.0"): return "C 7.0/7.1xx - untested"
    return "D 7.4xx+/2015 - needs new decoder"

t = collections.defaultdict(lambda: collections.Counter())
for j in uniq.values():
    f = arch_fmt.get(j["archive"], {})
    has = "has IFC" if f.get("ifc") else ("has STEP" if f.get("stp") else "no export")
    big = int(j["members"]) > 100
    t[tier(j["version"])][(has, big)] += 1
print("| readiness | models | >100 members | of which archive already has IFC | has STEP (no IFC) |\n|---|---:|---:|---:|---:|")
for k in sorted(t):
    c = t[k]
    tot = sum(c.values()); big = sum(v for (h, b), v in c.items() if b)
    ifc = sum(v for (h, b), v in c.items() if h == "has IFC"); stp = sum(v for (h, b), v in c.items() if h == "has STEP")
    print(f"| {k} | {tot} | {big} | {ifc} | {stp} |")
# what are the .stp files inside archives? sample names via formats only (names not stored) -> count archives
print("archives with .stp:", sum(1 for f in arch_fmt.values() if f.get("stp")), " with .ifc:", sum(1 for f in arch_fmt.values() if f.get("ifc")))
