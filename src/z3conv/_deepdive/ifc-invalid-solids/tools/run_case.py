#!/usr/bin/env python3
"""Local reproduction of the data-3 IFC worker + index-builder verdict for one model and one converter.
Runs the builder's own worker.process() (conversion ladder, step_check read-back, ifc_census, grade_join) with the
converter swapped, then build_index.classify_ifc() -> class + reasons. Nothing is uploaded.
usage: run_case.py CONVERTER.py INPUT_FILE SHA256 WORKDIR [--threads N] [--kit DIR]
prints one JSON line {class, reasons, issues, validate, step, join, sec, ...}"""
import sys, os, json, time, shutil, argparse, subprocess, signal
sys.dont_write_bytecode = True
ap = argparse.ArgumentParser()
ap.add_argument('conv'); ap.add_argument('input'); ap.add_argument('sha'); ap.add_argument('work')
ap.add_argument('--threads', default='2'); ap.add_argument('--kit', default=os.environ.get('KIT', '/Users/dhiren/Downloads/Deccan/z3conv/ifc'))
ap.add_argument('--coord', default=os.environ.get('COORD', '/Users/dhiren/Downloads/Deccan/z3conv/coord'))
ap.add_argument('--rb-max-mb', default=None)
a = ap.parse_args()
os.environ.setdefault('CONV_HOME', '/Users/dhiren/Downloads/Deccan/z3conv/ifc_v6/_env')
os.environ['IFC_THREADS'] = a.threads
if a.rb_max_mb:
    os.environ['RB_MAX_MB'] = a.rb_max_mb
os.environ.setdefault('INDEX_WORK', '/Users/dhiren/Downloads/Deccan/z3conv/_deepdive/ifc-invalid-solids/work/index')
sys.path.insert(0, a.kit)
import convfleet as cf
import worker as W


class FakeS3:
    def download_file(self, bucket, key, dst):
        shutil.copyfile(a.input, dst)


class FakeFleet:
    def run(self, jid, cmd, logf, timeout, stall=None, mem_frac=0.85, env=None, cwd=None):
        with open(logf, 'a') as lf:
            lf.write(f'\n$ {" ".join(map(str, cmd))[:600]}\n'); lf.flush()
            p = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, env=env, cwd=cwd, start_new_session=True)
            t0 = time.time(); last = -1; changed = t0; rc = None
            while rc is None:
                try:
                    rc = p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    t = time.time()
                    if t - t0 > timeout:
                        os.killpg(p.pid, signal.SIGKILL); p.wait(); rc = 124; break
                    if stall:
                        try: sz = os.path.getsize(logf)
                        except OSError: sz = last
                        if sz != last: last = sz; changed = t
                        elif t - changed > stall:
                            os.killpg(p.pid, signal.SIGKILL); p.wait(); rc = 125; break
        return rc

    def sh(self, cmd, timeout=600, env=None):
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return r.returncode, r.stdout, r.stderr

    def upload(self, path, key, ctype=None):
        pass


cf.s3 = FakeS3()
W.CONV = os.path.abspath(a.conv)
g = os.path.join(os.path.dirname(W.CONV), os.path.basename(W.CONV).replace('.py', '_guard.py'))
W.GUARD = g if os.path.exists(g) else W.CONV
os.makedirs(a.work, exist_ok=True)
job = {'id': a.sha, 'sha256': a.sha, 'input_key': 'local', 'size': os.path.getsize(a.input), 'kind': 'ifc', 'paths': [os.path.basename(a.input)]}
t0 = time.time()
try:
    res = W.process(FakeFleet(), job, a.work)
except MemoryError:
    res = {'status': 'fail', 'reason': 'out_of_memory'}
sec = round(time.time() - t0, 1)
sys.path.insert(0, a.coord)
import build_index as BI
row = BI.classify_ifc({'id': a.sha, 'sha256': a.sha, 'action': 'convert', 'size': job['size']}, res, None)
out = {'class': row.get('class'), 'reasons': row.get('reasons'), 'issues': row.get('issues'), 'standins': row.get('standins'),
       'coverage_all': row.get('coverage_all'), 'weight_ratio': row.get('weight_ratio'), 'graded_by': row.get('graded_by'),
       'status': res.get('status'), 'fail_reason': res.get('reason'), 'sec': sec,
       'step': res.get('step'), 'validate': res.get('validate'), 'join': res.get('join'), 'census': res.get('census'),
       'attempts': [{k: x.get(k) for k in ('rc', 'ok', 'sec', 'mode', 'kernel', 'converter', 'parts')} for x in res.get('attempts', [])],
       'input_fix': res.get('input_fix')}
json.dump(out, open(os.path.join(a.work, 'case.json'), 'w'), indent=1, default=str)
print(json.dumps({k: out[k] for k in ('class', 'reasons', 'issues', 'status', 'fail_reason', 'sec')}, default=str))
