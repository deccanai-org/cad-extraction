"""Re-convert every locally extracted test job with the exact-B-rep + holes pipeline and tabulate the results.
usage: python regen_exact.py <root> [out dir] [name regex or -] [parallel jobs]
  (finds every folder holding main/job_mtrl + subm/subm_idx; e.g. 4 parallel jobs need ~16 GB RAM for the largest)
Writes <out>/<name>_stage2.step (+ _pieces.csv, _preview.png, .log) and <out>/summary.md.
"""
import os, sys, re, subprocess, hashlib, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def jobs_under(top):
    seen = {}
    if os.name == "nt" and not top.startswith("\\\\?\\"):
        top = "\\\\?\\" + os.path.abspath(top)             # job folders nested past MAX_PATH (Marion County 7.122)
    for d, subs, files in os.walk(top):
        if os.path.basename(d) == "subm" and os.path.exists(os.path.join(d, "subm_idx")):
            job = os.path.dirname(d)
            if os.path.exists(os.path.join(job, "main", "job_mtrl")) and os.path.exists(os.path.join(job, "mem", "mem_idx")):
                # twins extracted twice (same mem_idx) are converted once
                h = hashlib.md5(open(os.path.join(job, "mem", "mem_idx"), "rb").read()).hexdigest()
                seen.setdefault(h, job)
            subs[:] = []
    return sorted(seen.values())


def main():
    top = sys.argv[1]
    out = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "out", "samples_exact"))
    only = re.compile(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] != "-" else None   # re-run matching names only
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 1             # parallel conversions (each is single-threaded)
    os.makedirs(out, exist_ok=True)
    todo, seen = [], collections.Counter()
    for job in jobs_under(top):
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", os.path.basename(job)).strip("_")
        seen[name] += 1
        if seen[name] > 1: name += f"_{seen[name]}"                    # twin extractions get their own outputs
        if only and not only.search(name):
            continue
        todo.append((name, job))
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=workers) as ex:
        rows = list(ex.map(lambda nj: run_one(*nj, out), todo))
    with open(os.path.join(out, "summary.md" if not only else "summary_rerun.md"), "w") as f:
        f.write("| job | version | exact / (plate+rolled+fastener) | skipped | holes cut | steel solids / SDS2 | solids valid | s |\n")
        f.write("|---|---|---:|---:|---:|---:|---:|---:|\n")
        for r in rows:
            tot = int(r["plate"]) + int(r["rolled"]) + int(r["fastener"])
            f.write(f"| {r['job']} | {r['version']} | {r['exact']} / {tot} | {r['skipped']} | {r['holes']} | {r['ratio']} | "
                    f"{r['valid']} / {r['shapes']} | {r['secs']} |\n")


def run_one(name, job, out):
    if True:
        step = os.path.join(out, f"{name}_stage2.step")
        p = subprocess.run([sys.executable, "-u", os.path.join(ROOT, "decode", "sds2_to_step.py"), job, "-o", step, "--stage", "2", "--verify"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=10800,
                           env=dict(os.environ, PYTHONUNBUFFERED="1"))
        txt = p.stdout
        open(os.path.join(out, f"{name}_stage2.log"), "w").write(txt)
        g = lambda pat, d="": (re.search(pat, txt) or [None, d])[1]
        r = dict(job=name, version=g(r"SDS2 version (\S+)"), exact=g(r"'exact': (\d+)", "0"),
                 plate=g(r"'plate': (\d+)", "0"), rolled=g(r"'rolled': (\d+)", "0"), fastener=g(r"'fastener': (\d+)", "0"),
                 skipped=g(r"'skipped': (\d+)", "?"), holes=g(r"'holes': (\d+)", "0"), ratio=g(r"ratio ([\d.]+)"),
                 shapes=g(r"(\d+) top-level shapes"), valid=g(r"BRep valid: (\d+)"), secs=g(r"converted in (\d+)s"),
                 ok="ok" if p.returncode == 0 else f"exit {p.returncode}")
        print(" | ".join(str(v) for v in r.values()), flush=True)
        return r


if __name__ == "__main__":
    main()
