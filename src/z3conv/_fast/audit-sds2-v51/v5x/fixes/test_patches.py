#!/usr/bin/env python3
"""audit-sds2-v5x: deployed (base/) vs patched convfleet / worker on the failure scenarios seen on the data-3 SDS2 fleet.
Runs the real _watchdog loop and _finish of both versions against stubbed /proc, S3 and host state (no network writes).
usage: python test_patches.py   (from the fixes dir; base/ holds the deployed files)"""
import os, sys, json, time, threading, importlib.util, tempfile, collections, ast, re

HERE = os.path.dirname(os.path.abspath(__file__))
GB = 1 << 30


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


class P:                                            # fake subprocess handle
    def __init__(self, pid): self.pid = pid


def make_fleet(cf, own_rss, legacy_rss, avail, total=495 * GB, legacy_rss_file=False, heartbeat_rss=0):
    """one worker process of the new runtime with one running job (own_rss) on a host where a legacy worker generation runs a
    job of legacy_rss (no registry; rss file only if legacy_rss_file; heartbeat rss = heartbeat_rss)"""
    fl = object.__new__(cf.Fleet)
    fl.rundir = tempfile.mkdtemp(); fl.total = total; fl.pipe = 'sds2'; fl.code = 'z3-sds2-v5.3-2026-10-01a'; fl.label = 'v5.3'
    fl.plock = threading.Lock(); fl.lock = threading.Lock(); fl.runq = collections.deque(maxlen=10)
    fl.procs = {'job_small': [P(111)]}; fl.running = {'job_small': {'need': 17 * GB, 'rss': own_rss}}; fl.killed = {}
    fl.disk_killed = set(); fl.others = {'by_pid': {}}
    if hasattr(cf.Fleet, '_spare'):
        fl.kill_min = max(4 * GB, total // 100); fl.kill_emergency = int(total * 0.02)
    legacy_job = {'id': 'job_big_legacy', 'need': 38 * GB, 'rss': heartbeat_rss, 'pid': 999, 'legacy': True}
    fl._host = lambda: {'jobs': [legacy_job, {'id': 'job_small', 'need': 17 * GB, 'rss': own_rss, 'pid': cf.PID}], 'n': 2}
    fl._write_reg = lambda: None
    fl.disk = lambda: (1000 * GB, 900 * GB)
    kills = []
    fl._kill = lambda p: kills.append(p.pid)
    if legacy_rss_file:
        json.dump({'pid': os.getpid(), 'max_rss': legacy_rss, 'at': time.time() + 3600}, open(os.path.join(fl.rundir, 'rss-999.json'), 'w'))
    cf.mem = lambda: (total, avail)
    cf.rss_tree = lambda pid: own_rss if pid == 111 else 0
    if hasattr(cf, 'proc_rss_max'):
        cf.proc_rss_max = lambda exclude: legacy_rss          # the legacy converter process as /proc shows it
        cf.tree_pids = lambda pid: {pid}
    cf.log = lambda msg: LOG.append(msg)
    return fl, kills


LOG = []


def run_watchdog(fl, secs=2.5):
    t = threading.Thread(target=fl._watchdog, daemon=True); t.start(); time.sleep(secs)


def watchdog_case(title, own, legacy, avail, **kw):
    out = {}
    for tag, path in (('deployed', os.path.join(HERE, 'base', 'convfleet.py')), ('patched', os.path.join(HERE, 'convfleet.py'))):
        cf = load(f'cf_{tag}_{abs(hash(title))}', path)
        fl, kills = make_fleet(cf, own, legacy, avail, **kw)
        LOG.clear(); run_watchdog(fl)
        out[tag] = {'killed_small_job': bool(kills), 'log': [l for l in LOG if 'WATCHDOG' in l][:2]}
    print(json.dumps({'case': title, **out}, indent=1))
    return out


res = {}
# A: the data-3 failure: own job 0.5 GB, legacy job 49 GB (no rss file, heartbeat without rss), MemAvailable 40 GB of 495 GB
res['A_mixed_host_small_own_job'] = watchdog_case('A mixed host: own 0.5 GB job, legacy 49 GB job, avail 40 GB', int(0.5 * GB), 49 * GB, 40 * GB)
# B: own job really is the hog (30 GB) and the legacy job is 10 GB -> both must kill it
res['B_own_job_is_hog'] = watchdog_case('B own 30 GB job is the largest, legacy 10 GB, avail 40 GB', 30 * GB, 10 * GB, 40 * GB)
# C: emergency (avail 5 GB < 2 % of RAM): even a small own job is killed when it is the largest visible
res['C_emergency'] = watchdog_case('C emergency: own 1 GB, nothing larger, avail 5 GB', 1 * GB, 0, 5 * GB)


# D: _finish after a memory kill on a job with a finished v5.1 result (MELBOURNE ff442ef1: 4 earlier kills, peak 2 GB)
def finish_case(title, peak_gb, prev_deferred):
    out = {}
    for tag, path in (('deployed', os.path.join(HERE, 'base', 'convfleet.py')), ('patched', os.path.join(HERE, 'convfleet.py'))):
        cf = load(f'cf_fin_{tag}_{abs(hash(title))}', path)
        fl, _ = make_fleet(cf, int(peak_gb * GB), 0, 40 * GB)
        fl.ST = 'st'; fl.killed = {'J': int(peak_gb * GB)}; fl.running = {'J': {'peak_rss': int(peak_gb * GB)}}
        store = {'st/results/J.json': {'id': 'J', 'status': 'ok', 'code': 'z3-sds2-v5.1-2026-10-01a', 'converter': {'label': 'v5.1'},
                                       'step': {'key': 'conversions/sds2-step/J/v5.1/x_stage2.step'}},
                 'st/deferred/J.json': prev_deferred}
        fl.getj = lambda k, bucket=None: json.loads(json.dumps(store.get(k))) if store.get(k) is not None else None
        fl.put = lambda k, o: store.__setitem__(k, o)
        fl.release = lambda jid: None
        fl.mem_need = lambda job: 17 * GB
        fl._finish({'id': 'J', 'size': 285 << 20, 'model_bytes': 285 << 20},
                   {'id': 'J', 'status': 'deferred', 'code': fl.code, 'peak_rss_gb': peak_gb})
        r = store['st/results/J.json']; d = store['st/deferred/J.json']
        out[tag] = {'result_status': r.get('status'), 'result_reason': r.get('reason'), 'result_step': (r.get('step') or {}).get('key'),
                    'alternatives': r.get('alternatives'), 'deferred_kills': d.get('kills'), 'kills_by_code': d.get('kills_by_code')}
    print(json.dumps({'case': title, **out}, indent=1))
    return out


res['D_spurious_5th_kill'] = finish_case('D 5th kill at 2 GB peak, finished v5.1 result, 4 earlier kills', 2.0, {'id': 'J', 'kills': 4, 'min_mem_bytes': 17 * GB})
res['E_real_5th_kill'] = finish_case('E 5th counted kill of this code at 20 GB peak, finished v5.1 result', 20.0,
                                     {'id': 'J', 'kills': 4, 'kills_by_code': {'z3-sds2-v5.3-2026-10-01a': 4}, 'min_mem_bytes': 32 * GB})


# F: worker best-of on VOID 2263534c (v4 est [2,0,0,0.0] vs v5.1 est [2,0,0,0.0004]) and 401 CONGRESS 693974d8
def worker_funcs(path):
    ns = {'json': json, 'collections': collections, 're': re, 'os': os}
    for node in ast.parse(open(path).read()).body:
        if isinstance(node, ast.FunctionDef):
            exec(compile(ast.Module(body=[node], type_ignores=[]), path, 'exec'), ns)
    return ns


def rec(ratio, man=True):
    r = {'status': 'ok', 'validate': {'invalid': 0}, 'stage2': {'steel_ratio': ratio}, 'inventory': {'skipped_by_reason': {}, 'standins_total': 29}}
    if man:
        r['manifest'] = {'skipped_by_reason': {}, 'standins_total': 29, 'weight': {'ratio': ratio}}
    return r


wd, wp = worker_funcs(os.path.join(HERE, 'base', 'worker.py')), worker_funcs(os.path.join(HERE, 'worker.py'))
for title, new, old in (('F VOID 2263534c v5.1 vs v4', rec(1.0004), rec(1.0, man=False)), ('G 401 CONGRESS 693974d8 v5.1 vs v4', rec(1.0112), rec(1.011, man=False)),
                        ('H real weight difference must still decide', rec(1.04), rec(1.01, man=False))):
    a_d, b_d = wd['est_class'](new), wd['est_class'](old)
    a_p, b_p = wp['best_key'](new), wp['best_key'](old)
    res[title] = {'deployed_keeps': 'new' if a_d <= b_d else 'old', 'patched_keeps': 'new' if a_p <= b_p else 'old',
                  'deployed_keys': [a_d, b_d], 'patched_keys': [a_p, b_p]}
    print(json.dumps({'case': title, **res[title]}, indent=1))

ok = (res['A_mixed_host_small_own_job']['deployed']['killed_small_job'] and not res['A_mixed_host_small_own_job']['patched']['killed_small_job']
      and res['B_own_job_is_hog']['patched']['killed_small_job'] and res['C_emergency']['patched']['killed_small_job']
      and res['D_spurious_5th_kill']['deployed']['result_reason'] == 'out_of_memory' and res['D_spurious_5th_kill']['patched']['result_status'] == 'ok'
      and res['E_real_5th_kill']['patched']['result_status'] == 'ok' and 'v5.3' in (res['E_real_5th_kill']['patched']['alternatives'] or {})
      and res['F VOID 2263534c v5.1 vs v4']['deployed_keeps'] == 'old' and res['F VOID 2263534c v5.1 vs v4']['patched_keeps'] == 'new'
      and res['G 401 CONGRESS 693974d8 v5.1 vs v4']['patched_keeps'] == 'new' and res['H real weight difference must still decide']['patched_keeps'] == 'old')
print('ALL EXPECTATIONS MET' if ok else 'EXPECTATION FAILED')
json.dump(res, open(os.path.join(HERE, 'test_patches_result.json'), 'w'), indent=1, default=str)
sys.exit(0 if ok else 1)
