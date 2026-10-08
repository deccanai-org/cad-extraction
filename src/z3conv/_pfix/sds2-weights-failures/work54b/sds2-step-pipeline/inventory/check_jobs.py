"""Extract specific jobs from (large) Disk-2 zips via a cached central directory, then preflight + stage-2 conversion
with --verify. usage: python check_jobs.py <workdir> <out_dir> <items.json>   items: [[label, archive, job_root], ...]"""
import os, sys, json, re, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cached_zip import open_cached

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
norm = lambda n: n.replace("\\", "/")
work, outd, items = sys.argv[1], sys.argv[2], json.load(open(sys.argv[3]))
os.makedirs(outd, exist_ok=True)
zips = {}
for label, archive, root in items:
    if archive not in zips:
        zips[archive] = open_cached("Disk-2/" + archive, os.path.join(work, "zcache"))
    z, f = zips[archive]
    before = f.fetched
    dest = "\\\\?\\" + os.path.abspath(os.path.join(work, label))
    pref = tuple(f"{root}/{d}/" for d in ("main", "mem", "subm"))
    for i in z.infolist():
        if norm(i.filename).startswith(pref) and not i.is_dir(): z.extract(i, dest)
    job = os.path.join(dest, *root.split("/"))
    v = re.match(rb"\s*version\s+([0-9.]+)", open(os.path.join(job, "main", "jsetup"), "rb").read(64))
    print(f"== {label}: version {v.group(1).decode() if v else '?'}, job files {(f.fetched - before) / 1e6:.1f} MB", flush=True)
    pf = subprocess.run([sys.executable, os.path.join(ROOT, "decode", "preflight.py"), job, "120"], capture_output=True, text=True)
    print("   preflight", [l for l in pf.stdout.splitlines() if l.startswith("{")][-1][:600], flush=True)
    out = os.path.join(outd, f"{label}_stage2.step")
    p = subprocess.run([sys.executable, "-u", os.path.join(ROOT, "decode", "sds2_to_step.py"), job, "-o", out, "--stage", "2", "--verify"],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    open(os.path.splitext(out)[0] + ".log", "w").write(p.stdout)
    for l in p.stdout.splitlines():
        if re.match(r"\s*(version|with solids|not built)", l) or "Error" in l: print("  ", l.strip()[:300], flush=True)
    json.dump({"label": label, "job": job[4:]}, open(os.path.join(outd, f"{label}.json"), "w"))
