#!/usr/bin/env python3
"""BOX (coverage-regression): run ONE DB1 model through a given converter kit exactly as the fleet worker does, without the
fleet (no claims, no result writes, no uploads to conversions/). Outputs stay on the box; the result JSON is copied to
s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/coverage-regression/ab/<tag>/<sha>.json

usage: ab_one.py KIT_DIR TAG JOB_JSON MODE      MODE = decode (convert_one only) | full (worker._process_inner)
"""
import os, sys, json, gzip, time, shutil, subprocess, traceback
kit, tag, jobp, mode = sys.argv[1:5]
sys.path.insert(0, os.path.abspath(kit))
os.environ.setdefault('CONV_HOME', '/opt/conv')
import worker                     # the kit's worker (imports the kit's convfleet)
cf = worker.cf
job = json.load(open(jobp))
jid = job['id']
BASE = os.environ.get('AB_WORK', '/work/agentwork/coverage-regression/ab')
d = os.path.join(BASE, tag, jid[:16]); shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
OUTP = 'cad-disk-extract/zenitude-data-3/_state/agentwork/coverage-regression/ab'


class FakeFleet:
    """the subset of convfleet.Fleet that worker._process_inner uses; uploads are kept local (never written to conversions/)"""
    ST = f'{cf.ROOT}/_state/conv/db1'

    def run(self, jid_, cmd, logf, timeout, stall=None, mem_frac=0.85, env=None, cwd=None):
        with open(logf, 'a') as lf:
            lf.write('\n$ ' + ' '.join(cmd) + '\n'); lf.flush()
            try:
                p = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, timeout=timeout, env=env, cwd=cwd)
                return p.returncode
            except subprocess.TimeoutExpired:
                return 124

    def sh(self, cmd, timeout=600, env=None):
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return p.returncode, p.stdout, p.stderr

    def upload(self, path, key, ctype=None):
        dst = os.path.join(d, 'up', key.replace('/', '__')[-180:])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(path, dst)

    def getj(self, key, bucket=None):
        return None


fl = FakeFleet()
t0 = time.time()
try:
    if mode == 'full':
        rec = worker._process_inner(fl, job, d)
    else:
        # decode only: identical command line to the worker's first stage
        db1 = os.path.join(d, 'in.db1'); ifc = os.path.join(d, 'model.ifc'); stats = os.path.join(d, 'convert.json')
        cf.s3.download_file(cf.B, job['input_key'], db1)
        rec = {'sha256': job['sha256']}
        got = cf.sha256_file(db1)
        if got != job['sha256']:
            raise RuntimeError(f'sha mismatch {got}')
        eng = worker.engine_of(db1); rec['engine'] = eng
        lay = worker.LAYOUTS[eng].get('layout')
        lp = os.path.join(d, 'layout.json'); json.dump(lay, open(lp, 'w'))
        vp = os.path.join(d, 'variants.json'); json.dump([v['layout'] for v in worker.LAYOUTS.values() if v.get('layout')], open(vp, 'w'))
        catp, ovmeta = worker.catalog_path(); rec['catalog_overlay'] = ovmeta
        dpy = worker.PY84 if os.path.exists(worker.PY84) else worker.PY
        rc = fl.run(jid, [dpy, os.path.join(kit, 'convert_one.py'), db1, ifc, catp, lp, stats, vp], os.path.join(d, 'log.txt'), 7200)
        cs = json.load(open(stats)) if os.path.exists(stats) else {}
        rec['convert_rc'] = rc
        rec['convert'] = {k: v for k, v in cs.items() if k not in ('layout', 'trace', 'parts_list')}
        rec['trace'] = cs.get('trace')
        plp = stats + '.parts.json.gz'
        if os.path.exists(plp):
            pl = json.load(gzip.open(plp, 'rt'))
            rec['decoded'] = worker.decoded_summary(pl)
        rec['status'] = 'ok' if rc == 0 and cs.get('status') == 'ok' else 'fail'
        rec['reason'] = None if rec['status'] == 'ok' else (cs.get('status') or f'rc {rc}')
except Exception as e:
    rec = {'status': 'error', 'error': f'{type(e).__name__}: {str(e)[:300]}', 'trace': traceback.format_exc()[-2000:]}
rec['id'] = jid; rec['ab_tag'] = tag; rec['ab_mode'] = mode; rec['ab_kit'] = os.path.abspath(kit); rec['ab_sec'] = round(time.time() - t0, 1)
out = os.path.join(BASE, tag, jid + '.json')
json.dump(rec, open(out, 'w'), default=str)
try:
    cf.s3.upload_file(out, cf.B, f'{OUTP}/{tag}/{jid}.json')
except Exception as e:
    print('upload failed', e)
print(tag, jid[:12], rec.get('status'), rec.get('reason'), rec['ab_sec'], flush=True)
