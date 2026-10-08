#!/usr/bin/env python3
"""One model through the data-3 IFC worker (worker.process: conversion ladder, step_check read-back, ifc_census,
grade_join) with the converter swapped, then the coordinator's classify_ifc with the LIVE rules.json -> class + reasons.
(adapted from the IFC improver's run_case.py; nothing is uploaded by the worker itself)
usage: rc.py CONVERTER.py INPUT_FILE SHA256 WORKDIR --kit DIR --coord DIR [--threads N] [--rb-max-mb N]"""
import sys, os, json, time, shutil, argparse, subprocess, signal
sys.dont_write_bytecode = True
ap = argparse.ArgumentParser()
ap.add_argument('conv'); ap.add_argument('input'); ap.add_argument('sha'); ap.add_argument('work')
ap.add_argument('--threads', default='2'); ap.add_argument('--kit', required=True); ap.add_argument('--coord', required=True)
ap.add_argument('--rb-max-mb', default=None)
a = ap.parse_args()
os.environ.setdefault('CONV_HOME', '/opt/conv')
os.environ['IFC_THREADS'] = a.threads
if a.rb_max_mb:
    os.environ['RB_MAX_MB'] = a.rb_max_mb
os.environ.setdefault('INDEX_WORK', os.path.join(a.work, '_index'))
sys.path.insert(0, a.kit)
import convfleet as cf
import worker as W

PEAK = {'rss_kb': 0}


class FakeS3:
    def download_file(self, bucket, key, dst):
        shutil.copyfile(a.input, dst)


def tree_rss_kb(pid):
    """RSS of a process tree (kB) from /proc"""
    tot = 0
    try:
        kids = {}
        for p in os.listdir('/proc'):
            if not p.isdigit():
                continue
            try:
                st = open('/proc/%s/stat' % p).read().rsplit(')', 1)[1].split()
                kids.setdefault(int(st[1]), []).append(int(p))
            except Exception:
                pass
        todo = [pid]
        while todo:
            q = todo.pop()
            try:
                for line in open('/proc/%d/status' % q):
                    if line.startswith('VmRSS:'):
                        tot += int(line.split()[1]); break
            except Exception:
                pass
            todo += kids.get(q, [])
    except Exception:
        pass
    return tot


class FakeFleet:
    ST = 'local'

    running = {}

    def run(self, jid, cmd, logf, timeout, stall=None, mem_frac=0.85, env=None, cwd=None, mem_max=None, **kw):
        with open(logf, 'a') as lf:
            lf.write(f'\n$ {" ".join(map(str, cmd))[:600]}\n'); lf.flush()
            p = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, env=env, cwd=cwd, start_new_session=True)
            t0 = time.time(); last = -1; changed = t0; rc = None; k = 0
            lim_kb = int(float(os.environ.get('RC_MEM_GB', '48')) * (1 << 20))
            while rc is None:
                try:
                    rc = p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    t = time.time(); k += 1
                    cur = tree_rss_kb(p.pid)
                    PEAK['rss_kb'] = max(PEAK['rss_kb'], cur)
                    if cur > lim_kb:
                        # memory watchdog (agent box budget): kill the process group like the fleet's memory kill
                        lf.write(f'\n[rc watchdog] tree RSS {cur >> 20} GB > {lim_kb >> 20} GB: killed\n'); lf.flush()
                        PEAK['killed'] = PEAK.get('killed', 0) + 1
                        os.killpg(p.pid, signal.SIGKILL); p.wait(); rc = -9; break
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

    def getj(self, key):
        return None


cf.s3 = FakeS3()
W.CONV = os.path.abspath(a.conv)
W.GUARD = W.CONV
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
try:
    BI.RULES.update(json.load(open(os.path.join(a.coord, 'rules.json'))))
except Exception as e:
    print('rules.json not loaded:', e, file=sys.stderr)
row = BI.classify_ifc({'id': a.sha, 'sha256': a.sha, 'action': 'convert', 'size': job['size']}, res, None)
out = {'class': row.get('class'), 'reasons': row.get('reasons'), 'issues': row.get('issues'), 'issues_info': row.get('issues_info'),
       'standins': row.get('standins'), 'coverage_members': row.get('coverage_members'), 'coverage_all': row.get('coverage_all'),
       'weight_ratio': row.get('weight_ratio'), 'graded_by': row.get('graded_by'), 'v6_tags': row.get('v6_tags'),
       'status': res.get('status'), 'fail_reason': res.get('reason'), 'sec': sec, 'peak_tree_rss_mb': PEAK['rss_kb'] >> 10, 'watchdog_kills': PEAK.get('killed', 0),
       'step': res.get('step'), 'validate': res.get('validate'), 'join': res.get('join'), 'census': res.get('census'),
       'attempts': [{k: x.get(k) for k in ('rc', 'ok', 'sec', 'mode', 'kernel', 'converter', 'parts')} for x in res.get('attempts', [])],
       'stats': (res.get('attempts') or [{}])[-1].get('stats'), 'input_fix': res.get('input_fix')}
json.dump(out, open(os.path.join(a.work, 'case.json'), 'w'), indent=1, default=str)
print(json.dumps({k: out[k] for k in ('class', 'reasons', 'issues', 'status', 'fail_reason', 'sec', 'peak_tree_rss_mb')}, default=str))
