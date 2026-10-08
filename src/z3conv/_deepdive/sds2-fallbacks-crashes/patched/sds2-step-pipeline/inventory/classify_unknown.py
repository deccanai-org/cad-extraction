"""Classify every job in the re-read unknown-version listings with the size fingerprint; write a per-job CSV and
print per-archive outcomes. An archive is 'convertible' if any job in it is complete, of a supported layout and not
a test/void copy with fewer than 25 members.
usage: python classify_unknown.py unknown_listings.jsonl unknown_classified.csv
"""
import sys, os, json, csv, re, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fingerprint as F

TEST = re.compile(r"(^|[\\/_ -])(test|temp|void|practice|training|sample|learning|backup_old)([\\/_ -]|$)", re.I)

rows, arch = [], {}
for line in open(sys.argv[1], encoding="utf-8"):
    r = json.loads(line)
    if "error" in r:
        arch[r["archive"]] = "listing error"; continue
    outcomes = []
    for root, j in r["jobs"].items():
        fam, why = F.family(j["job_mtrl"], j["mem_idx"], j["subm_idx"], j["max_mem"])
        if fam is None and why.startswith("no "): status = "incomplete"
        elif fam is None: status = "unrecognised layout"
        elif j["n_mem"] < 25 or TEST.search(root): status = "test/tiny"
        else: status = "convertible"
        outcomes.append(status)
        rows.append(dict(archive=r["archive"], job_root=root, family=fam or "", status=status, reason=why,
                         members=j["n_mem"], job_mtrl=j["job_mtrl"], mem_idx=j["mem_idx"], subm_idx=j["subm_idx"]))
    rank = ["convertible", "test/tiny", "unrecognised layout", "incomplete"]
    arch[r["archive"]] = min(outcomes, key=rank.index) if outcomes else "no job in listing"
with open(sys.argv[2], "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print("jobs:", len(rows), dict(collections.Counter(r["status"] for r in rows)))
print("families of complete jobs:", dict(collections.Counter(r["family"] for r in rows if r["family"])))
print("archives:", len(arch), dict(collections.Counter(arch.values())))
un = collections.Counter(r["reason"] for r in rows if r["status"] == "unrecognised layout")
if un: print("unrecognised layouts:", un.most_common(6))
