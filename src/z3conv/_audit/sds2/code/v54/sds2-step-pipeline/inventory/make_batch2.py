"""Second sampling batch: one job per rare version (inside big zips) + a random sample of the big version groups."""
import json, csv, random, collections, os
INV = os.path.dirname(os.path.abspath(__file__))
recs = {}
for line in open(os.path.join(INV, "disk2_archives.jsonl"), encoding="utf-8"):
    r = json.loads(line)
    if r["key"] not in recs or "error" in recs[r["key"]]:
        recs[r["key"]] = r
size = {k[len("Disk-2/"):]: r.get("size", 0) for k, r in recs.items()}
done = {json.loads(l)["archive"] for l in open(os.path.join(INV, "disk2_convertibility.jsonl"), encoding="utf-8")}
rows = [r for r in csv.DictReader(open(os.path.join(INV, "disk2_models.csv"), encoding="utf-8"))
        if r["source"] == "archive" and r["junk"] != "True" and int(r["members"]) >= 100]
items = []
# rare versions: prefer the smallest job >= 100 members; big zips are range-read
for v in ("7.021", "7.039", "7.208", "7.310", "7.516", "7.605", "7.613", "7.209", "7.115", "7.309"):
    rs = sorted((r for r in rows if r["version"] == v and r["archive"].lower().endswith(".zip")), key=lambda r: int(r["members"]))
    if rs:
        r = rs[0]; items.append([v, r["archive"], r["job_root"], size[r["archive"]]])
# big groups: random archives (7z <= 1.5 GB since they are downloaded whole; any zip)
random.seed(7)
for v, n in (("7.331", 10), ("7.312", 8), ("unknown", 10), ("2015.25", 6), ("7.245", 5), ("7.122", 2), ("7.135", 2)):
    key = (lambda r: r["version"] == v) if v != "2015.25" else (lambda r: "2015.25" in r["archive"])
    if v == "unknown": key = lambda r: not r["version"]
    cand = {r["archive"]: r for r in rows if key(r) and r["archive"] not in done and r["archive"].lower().endswith((".zip", ".7z"))
            and (r["archive"].lower().endswith(".zip") or size[r["archive"]] <= 1.5e9)}
    for a in random.sample(sorted(cand), min(n, len(cand))):
        r = cand[a]; items.append([v if v != "2015.25" else "2015.25-folder", a, r["job_root"], size[a]])
json.dump(items, open(os.path.join(INV, "batch2.json"), "w"), indent=0)
print(len(items), collections.Counter(i[0] for i in items), "GB to fetch (7z whole):", round(sum(i[3] for i in items if not i[1].lower().endswith('.zip') or i[3] < 1e9) / 1e9, 1))
