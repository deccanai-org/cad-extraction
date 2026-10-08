#!/usr/bin/env python3
"""Regression: run the kit worker's own process() (decode -> IFC -> STEP -> OCC check -> census -> join) for each job with a
given kit directory, then classify with the coordinator's build_index.classify_db1 -> class / standins / needs.
  regress.py KIT_DIR JOBS_JSON OUT_JSONL [slots]
Uploads nothing (FakeFleet.upload copies into OUT_DIR/files/<jid>/)."""
import sys, os, json, threading, time, shutil, traceback, importlib.util, concurrent.futures as cfut
kit = os.path.abspath(sys.argv[1]); jobs = json.load(open(sys.argv[2])); outp = sys.argv[3]; slots = int(sys.argv[4]) if len(sys.argv) > 4 else 4
sys.path.insert(0, kit)
os.environ.setdefault('INDEX_WORK', '/tmp/index_work')
import convfleet as cf
spec = importlib.util.spec_from_file_location('kitworker', os.path.join(kit, 'worker.py')); W = importlib.util.module_from_spec(spec); spec.loader.exec_module(W)
sys.path.insert(0, os.environ.get('COORD_DIR', '/opt/v2/coord'))
import build_index as BI
try:
    BI.RULES.update(json.load(open(os.path.join(os.environ.get('COORD_DIR', '/opt/v2/coord'), 'rules.json'))))
except Exception:
    pass
OUTD = os.path.splitext(outp)[0] + '_files'; os.makedirs(OUTD, exist_ok=True)

class FakeFleet:
    def __init__(self):
        self.total = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES'); self.lock = threading.Lock(); self.plock = threading.Lock()
        self.procs = {}; self.running = {}; self.killed = set(); self.disk_killed = set(); self.stop_now = False; self.job_cores = 4
    run = cf.Fleet.run; _kill = cf.Fleet._kill; sh = cf.Fleet.sh
    def upload(self, path, key, ctype=None):
        jid = None
        for part in key.split('/'):
            if len(part) >= 64: jid = part[:64]
        d = os.path.join(OUTD, (jid or 'misc')); os.makedirs(d, exist_ok=True)
        try: shutil.copy(path, os.path.join(d, os.path.basename(key)))
        except Exception: pass

fl = FakeFleet(); lock = threading.Lock()
done = set()
if os.path.exists(outp):
    for l in open(outp):
        try: done.add(json.loads(l)['id'])
        except Exception: pass

def one(job):
    jid = job['id']; d = os.path.join('/opt/v2/regwork', os.path.basename(kit), jid); shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    t = time.time()
    try:
        rec = getattr(W, '_process_inner', W.process)(fl, job, d)
    except Exception as e:
        rec = {'status': 'fail', 'reason': 'regress_exception', 'error': traceback.format_exc()[-1500:]}
    rec['id'] = jid; rec['sha256'] = job['sha256']; rec['sec'] = round(time.time() - t, 1); rec['code'] = getattr(W, 'CODE', None)
    try:
        c = {'action': 'convert', 'sha256': job['sha256'], 'id': jid, 'size': job.get('size'), 'paths': job.get('paths') or [], 'n_paths': job.get('n_paths')}
        row = BI.classify_db1(c, rec, None)
    except Exception as e:
        row = {'class': None, 'error': traceback.format_exc()[-800:]}
    small = {k: rec.get(k) for k in ('id', 'status', 'reason', 'engine', 'sec', 'code', 'decoded', 'step', 'excluded_elements', 'rescue', 'error', 'trace', 'log_tail')}
    small['convert'] = {k: (rec.get('convert') or {}).get(k) for k in ('status', 'members', 'written', 'sources', 'skipped', 'bolt_stats', 'axis_mismatch_dropped', 'decode_sec')}
    small['validate'] = {k: (rec.get('validate') or {}).get(k) for k in ('read_status', 'roots', 'solids', 'invalid_solids', 'grade', 'bbox')}
    small['grade'] = {k: (row or {}).get(k) for k in ('class', 'corpus', 'coverage_members', 'coverage_connections', 'coverage_all', 'standins', 'needs', 'issues', 'reasons', 'parts_source', 'parts_step', 'invalid_solids', 'error')}
    small['src'] = job.get('src'); small['tag'] = job.get('tag')
    with lock:
        with open(outp, 'a') as fo: fo.write(json.dumps(small, default=str) + '\n')
    shutil.rmtree(d, ignore_errors=True)
    return small

todo = [j for j in jobs if j['id'] not in done]
print('jobs', len(todo), 'kit', kit, 'code', getattr(W, 'CODE', None), flush=True)
with cfut.ThreadPoolExecutor(slots) as ex:
    for r in ex.map(one, todo):
        print(r['id'][:12], r.get('engine'), r.get('status'), r.get('reason'), 'class', r['grade'].get('class'), r.get('sec'), flush=True)
print('DONE', flush=True)
