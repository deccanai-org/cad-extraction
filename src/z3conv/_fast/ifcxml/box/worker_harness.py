#!/usr/bin/env python3
"""worker_harness.py - run the PATCHED fleet worker's per-job function (worker._process_inner: download -> sha check ->
unpack -> sniff -> ifcxml2spf -> SPF path -> ifc2step6 -> step_check -> ifc_census -> grade_join) on real jobs, without
the fleet loop and WITHOUT publishing: every fl.upload() is redirected below agentwork/ifcxml/harness/uploads/<key>
(nothing is written to conversions/ or _state/conv/), results go to agentwork/ifcxml/harness/results/<sha>.json.

    worker_harness.py KITDIR JOBS.json [--procs N]
KITDIR: the kit as published in s3://annotationprod/cad-disk-extract/_control/z3conv/ifc/ with worker.py replaced by the
patched one and ifcxml2spf.py added.
"""
import os, sys, json, time, subprocess, argparse, traceback
from concurrent.futures import ThreadPoolExecutor

ap = argparse.ArgumentParser()
ap.add_argument('kit')
ap.add_argument('jobs')
ap.add_argument('--procs', type=int, default=3)
a = ap.parse_args()
sys.path.insert(0, os.path.abspath(a.kit))
os.environ.setdefault('CONV_HOME', '/opt/conv')
import convfleet as cf
import worker

HARN = 'cad-disk-extract/zenitude-data-3/_state/agentwork/ifcxml/harness'
WORK = os.path.abspath('work/harness')


class FakeFleet:
    ST = f'{cf.ROOT}/_state/conv/ifc'

    def __init__(self):
        self.uploads = []

    def run(self, jid, cmd, logf, timeout, stall=None, mem_frac=0.85, env=None, cwd=None):
        with open(logf, 'a') as lf:
            lf.write('\n$ %s\n' % ' '.join(map(str, cmd))[:600])
            lf.flush()
            try:
                return subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, env=env, cwd=cwd, timeout=timeout).returncode
            except subprocess.TimeoutExpired:
                return 124

    def sh(self, cmd, timeout=600, env=None):
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return r.returncode, r.stdout, r.stderr

    def upload(self, path, key, ctype=None):
        k2 = f'{HARN}/uploads/{key}'                 # redirected: the harness never publishes
        assert k2.startswith('cad-disk-extract/zenitude-data-3/_state/agentwork/ifcxml/'), k2
        self.uploads.append([key, k2, os.path.getsize(path)])
        cf.s3.upload_file(path, cf.B, k2)

    def getj(self, key, bucket=cf.B):
        return None


def one(job):
    fl = FakeFleet()
    d = os.path.join(WORK, job['id'][:12])
    os.makedirs(d, exist_ok=True)
    t0 = time.time()
    try:
        r = worker._process_inner(fl, job, d)
    except Exception:
        r = {'status': 'harness_error', 'error': traceback.format_exc()[-2000:]}
    r = dict(r, id=job['id'], code=worker.CODE, harness_sec=round(time.time() - t0, 1), redirected_uploads=fl.uploads)
    p = os.path.join(WORK, job['id'][:12] + '.result.json')
    with open(p, 'w') as f:
        json.dump(r, f, indent=1, default=str)
    cf.s3.upload_file(p, cf.B, f'{HARN}/results/{job["id"]}.json')
    print(time.strftime('%H:%M:%S'), job['id'][:12], r.get('status'), r.get('reason'), r.get('harness_sec'), flush=True)
    return r


jobs = json.load(open(a.jobs))
print('worker CODE', worker.CODE, 'converter', os.path.basename(worker.CONV), 'xml2spf', os.path.exists(worker.XML2SPF), flush=True)
with ThreadPoolExecutor(a.procs) as ex:
    res = list(ex.map(one, jobs))
summ = [{k: r.get(k) for k in ('id', 'status', 'reason', 'detail', 'format', 'input_fix', 'harness_sec')} for r in res]
for r, s in zip(res, summ):
    s['ifcxml'] = {k: (r.get('ifcxml') or {}).get(k) for k in ('status', 'rc', 'schema', 'instances', 'dangling_references')}
    s['step_parts'] = (r.get('step') or {}).get('parts')
    s['coverage'] = (r.get('join') or {}).get('coverage')
    s['validate_grade'] = (r.get('validate') or {}).get('grade')
    s['census_products'] = (r.get('census') or {}).get('products')
p = os.path.join(WORK, 'summary.json')
with open(p, 'w') as f:
    json.dump(summ, f, indent=1, default=str)
cf.s3.upload_file(p, cf.B, f'{HARN}/summary.json')
print('HARNESS_DONE', flush=True)
