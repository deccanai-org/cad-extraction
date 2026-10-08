"""Show idx slot section field values vs IFC sections, and look for section names in main/job_mtrl."""
import os, sys, csv, collections, struct, re

job, pairs_csv = sys.argv[1], sys.argv[2]
SLOT = 2494
md = os.path.join(job, "mem")
idx = open(os.path.join(md, "mem_idx"), "rb").read()
m = collections.defaultdict(collections.Counter)
for r in csv.DictReader(open(pairs_csv)):
    n = int(r["mem_id"])
    raw = idx[n * SLOT + 0x1d0:n * SLOT + 0x1d8]
    m[raw.hex()][r["section"]] += 1
for k, c in sorted(m.items(), key=lambda kv: -sum(kv[1].values()))[:15]:
    print(k, dict(c.most_common(3)))
jm = open(os.path.join(job, "main", "job_mtrl"), "rb").read()
print("job_mtrl", len(jm))
for s in ("W18x35", "W14x455", "W24x55"):
    print(s, [hex(x.start()) for x in re.finditer(re.escape(s.encode()), jm)][:5])
print([(hex(x.start()), x.group().decode()) for x in re.finditer(rb"[ -~]{4,}", jm[:6000])][:40])
