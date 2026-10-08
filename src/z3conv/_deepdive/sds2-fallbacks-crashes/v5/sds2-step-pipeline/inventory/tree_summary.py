"""Summarise an `aws s3 ls --recursive` listing into a folder tree with counts, sizes and formats.

usage: python tree_summary.py <listing.txt> <out.md> [prefix]
"""
import sys, collections, os

MODEL_EXT = {
    "7z": "archive", "zip": "archive", "rar": "archive", "jft": "archive(sds2 packed job)",
    "ifc": "IFC", "stp": "STEP", "step": "STEP", "db1": "Tekla", "tsd": "Tekla",
    "rvt": "Revit", "dwg": "DWG", "dxf": "DXF", "nc1": "DSTV NC1", "kss": "KISS",
    "sdnf": "SDNF", "cis": "CIS/2", "skp": "SketchUp", "nwd": "Navisworks", "nwc": "Navisworks",
    "pdf": "PDF",
}

def ext_of(key):
    base = key.rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""

def load(path, prefix):
    rows = []
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            parts = line.rstrip("\n").split(None, 3)
            if len(parts) < 4 or not parts[2].isdigit():
                continue
            key = parts[3]
            if key.endswith("/") or not key.startswith(prefix):
                continue
            rows.append((int(parts[2]), key[len(prefix):]))
    return rows

def gb(n): return f"{n/1e9:,.1f}"

def main():
    src, out = sys.argv[1], sys.argv[2]
    prefix = sys.argv[3] if len(sys.argv) > 3 else "Disk-2/"
    rows = load(src, prefix)
    # aggregate at depth 1, 2, 3
    agg = collections.defaultdict(lambda: [0, 0, collections.Counter(), collections.Counter(), set()])
    jobs_loose = set()
    for size, key in rows:
        p = key.split("/")
        e = ext_of(key)
        if key.lower().endswith("/main/jsetup"):
            jobs_loose.add(key[: -len("/main/jsetup")])
        for d in (1, 2, 3):
            if len(p) > d:
                a = agg["/".join(p[:d])]
                a[0] += 1; a[1] += size; a[2][e] += 1
                if e in MODEL_EXT: a[3][e] += size
                if len(p) > d + 1: a[4].add(p[d])
    L = []
    L.append(f"# Folder tree: s3://bim-proprietary-data/{prefix}\n")
    L.append(f"Total: {len(rows):,} files, {gb(sum(s for s,_ in rows))} GB. Loose (unarchived) SDS2 jobs: {len(jobs_loose)}\n")
    def fmt_ext(c):
        return ", ".join(f"{k or '(none)'}:{v:,}" for k, v in c.most_common(8))
    for top in sorted([k for k in agg if k.count("/") == 0], key=lambda k: -agg[k][1]):
        a = agg[top]
        L.append(f"\n## {top}  —  {a[0]:,} files, {gb(a[1])} GB, {len(a[4])} subfolders\n")
        L.append(f"formats: {fmt_ext(a[2])}\n")
        L.append("\n| subfolder | files | GB | subfolders | archives | top formats |\n|---|---:|---:|---:|---:|---|")
        subs = sorted([k for k in agg if k.startswith(top + "/") and k.count("/") == 1], key=lambda k: -agg[k][1])
        for s in subs:
            b = agg[s]
            arch = b[2]["7z"] + b[2]["zip"] + b[2]["rar"] + b[2]["jft"]
            L.append(f"| {s.split('/',1)[1]} | {b[0]:,} | {gb(b[1])} | {len(b[4])} | {arch:,} | {fmt_ext(b[2])} |")
    # global format table
    tot = collections.Counter(); totsz = collections.Counter()
    for size, key in rows:
        e = ext_of(key); tot[e] += 1; totsz[e] += size
    L.append("\n## Formats across the disk (model-relevant)\n\n| ext | kind | files | GB |\n|---|---|---:|---:|")
    for e, kind in MODEL_EXT.items():
        if tot[e]:
            L.append(f"| .{e} | {kind} | {tot[e]:,} | {gb(totsz[e])} |")
    L.append("\n## Loose SDS2 jobs\n")
    L += [f"- {j}" for j in sorted(jobs_loose)]
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"wrote {out}: {len(rows)} files")

if __name__ == "__main__":
    main()
