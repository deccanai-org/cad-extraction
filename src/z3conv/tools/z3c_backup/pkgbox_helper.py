import os, sys, json, time, signal, socket, random, datetime, traceback
sys.path.insert(0, '/opt/pkgphelper/kit')
from multiprocessing import Pool
import pkg, pkgcore as pc
assert pc.TIER == 'partial' and pc.ROUTE == '3d_partial'
D = '/opt/pkgphelper'; MAXSZ = float(os.environ.get('PKGH_MAXSZ', '3e9')); PROCS = int(os.environ.get('PKGH_PROCS', '4')); HOST = socket.gethostname()
MINMEM = float(os.environ.get('PKGH_MINMEM', '60')); ADS = os.environ.get('PKGH_ADAPTERS', 'zen3').split(',')
JKS = {ad: (pkg.JOBS_KEY if ad == 'zen3' else pkg.JOBS_KEY.replace('/jobs.json', f'/jobs_{ad}.json')) for ad in ADS}; RP = pkg.JOBS_KEY.rsplit('/', 1)[0] + '/results/'
TRANSIENT = ('SSLError', 'ConnectionError', 'ReadTimeout', 'EndpointConnectionError', 'IncompleteRead', 'ProtocolError', 'ResponseStreamingError')
def log(*a): print(datetime.datetime.utcnow().strftime('%H:%M:%S'), *a, flush=True)
def mem_gb():
    for l in open('/proc/meminfo'):
        if l.startswith('MemAvailable'): return int(l.split()[1]) / 1048576
def term(*a): raise SystemExit(0)
def one(arg):
    job, ad = arg
    signal.signal(signal.SIGTERM, term)
    if pc.head(pc.BUCKET, f"{RP}{job['id']}.json"): return job['id'], 'already_done', 0
    if pc.head(pc.BUCKET, f"{pc.PSTATE}/locks/{job['project_id']}.json"): return job['id'], 'locked_elsewhere', 0
    while mem_gb() < MINMEM: time.sleep(30)
    r = None
    for attempt in range(4):
        try:
            r = pkg.package_job(job, workdir=f"{D}/work/{job['id']}")
        except Exception as e:
            tb = traceback.format_exc()[-1200:]
            r = {'project_id': job['project_id'], 'status': 'fail', 'reason': 'packager_exception', 'error': f'{type(e).__name__}: {e}'[:300], 'trace': tb}
            if any(t in tb for t in TRANSIENT) and attempt < 3: time.sleep(30 * (attempt + 1)); continue
        break
    if r.get('status') == 'retry': return job['id'], 'locked_elsewhere', 0
    out = dict(r); out.pop('verify', None) if r.get('status') == 'ok' else None
    out.update(id=job['id'], pipeline='package_partial', adapter=ad, finished=datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'), recorded_by=f'helper:{HOST}')
    pc.s3c().put_object(Bucket=pc.BUCKET, Key=f"{RP}{job['id']}.json", Body=json.dumps(out, default=str).encode(), ContentType='application/json')
    ap = r.get('apply') or {}
    log(job['id'], r.get('status'), r.get('reason') or r.get('note'), 'copied', ap.get('copied'), (r.get('verify') or {}).get('checks'), job['project_id'][:70])
    return job['id'], r.get('status'), ap.get('copied') or 0
idle = 0
while not os.path.exists(f'{D}/stop'):
    todo = []
    for ad, jk in JKS.items():
        jobs = (pc.get_json(pc.BUCKET, jk) or {}).get('jobs') or []
        todo += [(j, ad) for j in jobs if (j.get('size') or 0) <= MAXSZ]
    random.Random(HOST).shuffle(todo)
    log('job lists', {ad: 1 for ad in JKS}, 'todo', len(todo))
    done_any = False
    with Pool(PROCS, maxtasksperchild=1) as pool:
        for jid, st, n in pool.imap_unordered(one, todo):
            if st in ('ok', 'fail'): done_any = True
    idle = 0 if done_any else idle + 1
    if idle >= 3: log('nothing left: exiting'); break
    time.sleep(300)
