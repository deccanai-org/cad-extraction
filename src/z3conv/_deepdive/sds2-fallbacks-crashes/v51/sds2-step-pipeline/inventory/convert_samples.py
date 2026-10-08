"""Download a few Disk-2 archives, extract only their SDS2 job folders, and run the full stage-2 conversion + verify.
STEP files go to out/samples/<name>_stage2.step; the downloaded archive and extracted job are deleted afterwards.
usage: python convert_samples.py <workdir> <items.json>   (items: [[version, archive, job_root], ...])
"""
import os, sys, json, shutil, subprocess, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sample_convertibility import extract

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out", "samples")

if __name__ == "__main__":
    work, items = sys.argv[1], json.load(open(sys.argv[2]))
    os.makedirs(OUT, exist_ok=True)
    for v, archive, job_root in items:
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", job_root.split("/")[-1]).strip("_")
        dest = "\\\\?\\" + os.path.abspath(os.path.join(work, name))
        shutil.rmtree(dest, ignore_errors=True); os.makedirs(dest, exist_ok=True)
        out = os.path.join(OUT, f"{name}_stage2.step")
        log = open(os.path.join(OUT, f"{name}_stage2.log"), "w")
        try:
            job = extract(archive, job_root, dest)
            print(f"== {v} {archive}", flush=True)
            p = subprocess.run([sys.executable, "-u", os.path.join(ROOT, "decode", "sds2_to_step.py"), job, "-o", out, "--stage", "2", "--verify"],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=7200)
            keep = [l for l in p.stdout.splitlines() if re.match(r"(version|converted|  |\S+\.step:)", l) and "***" not in l]
            log.write(p.stdout); print("\n".join(keep), flush=True)
        except Exception as e:
            print(f"== {v} {archive} FAILED {type(e).__name__}: {e}", flush=True)
        log.close()
        shutil.rmtree(dest, ignore_errors=True)
