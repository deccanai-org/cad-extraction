#!/usr/bin/env python3
"""bench harness: run the fleet's job.py (local mode: nothing written to S3) for a list of models with a given code dir.

usage: run_local.py CODE_DIR IDS_FILE OUT_DIR [--jobs J] [--par P]
  IDS_FILE: JSON list of job dicts {id, pid, step, ifc, bytes, cls, gen} (e.g. from triage.json examples / regression.json)
  OUT_DIR/<id>/ gets the model's out folder (w/out/<stem>/ moved here) + summary.json + job.log
P models at a time (default 4), each with J worker processes (default 8)."""
import json, os, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
code, idsf, out = os.path.abspath(sys.argv[1]), sys.argv[2], os.path.abspath(sys.argv[3])
J = int(sys.argv[sys.argv.index('--jobs') + 1]) if '--jobs' in sys.argv else 8
P = int(sys.argv[sys.argv.index('--par') + 1]) if '--par' in sys.argv else 4
HERE = os.path.dirname(os.path.abspath(__file__))
jobs = json.load(open(idsf))
os.makedirs(out, exist_ok=True)
def one(j):
    jd = os.path.join(out, j['id'] + '.job'); shutil.rmtree(jd, ignore_errors=True); os.makedirs(jd)
    json.dump(dict(j, gen=j.get('gen', 1), cls=j.get('cls', 'S'), J=J, mem=0, code_dir=code, code_version=os.path.basename(code)),
              open(os.path.join(jd, 'job.json'), 'w'))
    t = time.time()
    rc = subprocess.call(['/opt/pm/venv/bin/python', os.path.join(HERE, 'job.py'), jd], env=dict(os.environ, PMX_LOCAL='1'),
                         stdout=open(os.path.join(jd, 'stdout.log'), 'w'), stderr=subprocess.STDOUT)
    dst = os.path.join(out, j['id']); shutil.rmtree(dst, ignore_errors=True)
    src = os.path.join(jd, 'w', 'out', j['id'][:16])
    if os.path.isdir(src): shutil.move(src, dst)
    else: os.makedirs(dst)
    for f in ('summary.json', 'job.log', 'stdout.log'):
        if os.path.exists(os.path.join(jd, f)): shutil.copy(os.path.join(jd, f), dst)
    shutil.rmtree(jd, ignore_errors=True)
    s = json.load(open(os.path.join(dst, 'summary.json'))) if os.path.exists(os.path.join(dst, 'summary.json')) else {}
    print(f"{j['id'][:16]} rc={rc} perfect={s.get('perfect')} reasons={s.get('reasons')} status={s.get('status')} {time.time()-t:.0f}s", flush=True)
with ThreadPoolExecutor(P) as ex: list(ex.map(one, jobs))
