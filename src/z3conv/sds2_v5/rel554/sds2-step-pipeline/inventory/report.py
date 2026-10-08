"""Aggregate probe_archives.py output + loose listing into a model inventory.

usage: python report.py <listing.txt> <archives.jsonl> <out_prefix> [prefix]
writes <out_prefix>_models.csv (one row per SDS2 job found) and <out_prefix>_models.md
"""
import sys, json, re, csv, collections

IFC_DONE = re.compile(r"binney|binny|mssu", re.I)   # models already converted via IFC


def ver_from_path(key):
    m = re.search(r"SDS_Jobs_([0-9.]+)", key)
    return m.group(1) if m else ""


def norm_name(root, archive_key):
    base = (root.rstrip("/").rsplit("/", 1)[-1] if root else archive_key.rsplit("/", 1)[-1].rsplit(".", 1)[0])
    n = base.lower()
    n = re.sub(r"[_\s-]*(job|backup|bkp|bak)\b.*$", "", n)
    n = re.sub(r"[_\s-]*\d{6,8}.*$", "", n)
    return re.sub(r"[^a-z0-9]+", " ", n).strip() or base.lower()


def area(key, prefix):
    p = key[len(prefix):].split("/")
    if p[0] == "Completed_Jobs_Data" and len(p) > 2:
        return f"{p[0]}/{p[1]}"
    if p[0] == "Completed_Projects_Data" and len(p) > 2:
        return f"{p[0]}/{p[1]}"
    return p[0]


def main():
    listing, arch, outp = sys.argv[1:4]
    prefix = sys.argv[4] if len(sys.argv) > 4 else "Disk-2/"
    jobs = []
    other = collections.Counter()
    stats = collections.Counter()
    err = []
    recs = {}
    for line in open(arch, encoding="utf-8"):
        r = json.loads(line)
        # several probe runs may have written the same key; keep a successful record over an error
        if r["key"] not in recs or "error" in recs[r["key"]]:
            recs[r["key"]] = r
    for r in recs.values():
        stats["archives"] += 1
        if "error" in r:
            err.append(r); continue
        if "skipped" in r:
            stats["skipped_" + r["skipped"]] += 1; continue
        for e, c in r.get("formats", {}).items():
            other[e] += c
        if r.get("tekla_model_dirs"):
            stats["tekla_models_in_archives"] += r["tekla_model_dirs"]
        if not r["jobs"]:
            stats["archives_without_job"] += 1
        for root, j in r["jobs"].items():
            jobs.append(dict(source="archive", archive=r["key"][len(prefix):], job_root=root,
                             area=area(r["key"], prefix), version=j.get("version") or ver_from_path(r["key"]),
                             version_src="jsetup" if j.get("version") else ("folder" if ver_from_path(r["key"]) else ""),
                             members=j.get("mem_files", 0), files=j.get("files", 0),
                             gb=round(j.get("bytes", 0) / 1e9, 2), name=norm_name(root, r["key"])))
    # loose jobs
    for line in open(listing, encoding="utf-8-sig", errors="replace"):
        p = line.rstrip("\n").split(None, 3)
        if len(p) == 4 and p[3].lower().endswith("/main/jsetup") and p[3].startswith(prefix):
            root = p[3][: -len("/main/jsetup")]
            jobs.append(dict(source="loose", archive="", job_root=root[len(prefix):], area=area(p[3], prefix),
                             version=ver_from_path(root), version_src="folder" if ver_from_path(root) else "",
                             members=0, files=0, gb=0, name=norm_name(root, root)))
    for j in jobs:
        j["ifc_done"] = bool(IFC_DONE.search(j["name"]))
        j["junk"] = bool(re.search(r"train|practice|test|temp|sample|void|gather", j["name"] + " " + j["job_root"], re.I))

    with open(outp + "_models.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(jobs[0].keys()))
        w.writeheader(); w.writerows(jobs)

    uniq = {}
    for j in jobs:
        k = j["name"]
        if k not in uniq or j["members"] > uniq[k]["members"]:
            uniq[k] = j
    good = [j for j in uniq.values() if not j["ifc_done"] and not j["junk"]]

    L = ["# SDS2 model inventory — Disk-2\n",
         f"- archives probed: {stats['archives']:,} (errors: {len(err)}, archives with no SDS2 job: {stats['archives_without_job']:,})",
         f"- SDS2 job instances found: **{len(jobs):,}** ({sum(j['source']=='loose' for j in jobs)} loose, rest inside archives)",
         f"- distinct job names: **{len(uniq):,}**; excluding IFC-already-converted ({sum(j['ifc_done'] for j in uniq.values())}) "
         f"and training/test/void copies ({sum(j['junk'] and not j['ifc_done'] for j in uniq.values())}): **{len(good):,} candidate models**",
         f"- total members (mem/ records) in candidates: {sum(j['members'] for j in good):,}\n"]
    L.append("## Candidates by version\n\n| version | models | members | median members |\n|---|---:|---:|---:|")
    byv = collections.defaultdict(list)
    for j in good:
        byv[j["version"] or "unknown"].append(j["members"])
    for v in sorted(byv, key=lambda v: [int(x) if x.isdigit() else 0 for x in v.split(".")]):
        m = sorted(byv[v]); L.append(f"| {v} | {len(m):,} | {sum(m):,} | {m[len(m)//2]:,} |")
    L.append("\n## Candidates by folder\n\n| folder | models | members |\n|---|---:|---:|")
    bya = collections.defaultdict(list)
    for j in good:
        bya[j["area"]].append(j["members"])
    for a in sorted(bya, key=lambda a: -len(bya[a])):
        L.append(f"| {a} | {len(bya[a]):,} | {sum(bya[a]):,} |")
    L.append("\n## Size distribution (members per candidate model)\n\n| members | models |\n|---|---:|")
    bins = [(0, 0), (1, 100), (101, 500), (501, 2000), (2001, 10000), (10001, 10**9)]
    for lo, hi in bins:
        c = sum(lo <= j["members"] <= hi for j in good)
        L.append(f"| {lo:,}–{hi:,} | {c:,} |" if hi < 10**9 else f"| >{lo-1:,} | {c:,} |")
    L.append("\n## Other formats found *inside* archives\n\n| ext | files |\n|---|---:|")
    for e, c in other.most_common():
        L.append(f"| .{e} | {c:,} |")
    L.append(f"\nTekla model folders (.db1) inside Disk-2 archives: {stats['tekla_models_in_archives']:,}\n")
    if err:
        L.append("## Probe errors\n")
        L += [f"- {e['key'][len(prefix):]} ({e['size']/1e9:.1f} GB): {e['error']}" for e in err]
    open(outp + "_models.md", "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L[:6]))

if __name__ == "__main__":
    main()
