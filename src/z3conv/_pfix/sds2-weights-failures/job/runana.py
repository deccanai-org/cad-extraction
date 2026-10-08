#!/usr/bin/env python3
"""Fetch SDS2 job folders (same layout rules as the fleet worker) and run a per-job command on them in parallel,
memory-aware; upload each job's JSON to s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/
sds2-weights-failures/<tag>/<id>.json (+ log).

usage: runana.py TAG IDS_FILE MODE [WORKERS] [MEM_GB]
  MODE ana:<decode_dir>          wdump.py analysis with that decode dir
  MODE conv:<pipeline_dir>       full fleet command: sds2_to_step.py <job> -o X_stage2.step --stage 2 --verify (+ manifest)
"""
import os, sys, json, gzip, time, subprocess, threading, re, shutil
import boto3
from botocore.config import Config
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=64, retries={'max_attempts': 20, 'mode': 'standard'}))
B = 'bim-proprietary-data'
W = '/work/agentwork/sds2-weights-failures'
RES = 'cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-weights-failures'
PY = f'{W}/env/bin/python'
CANON = {"main", "mem", "subm", "jsetup", "job_mtrl", "mem_idx", "subm_idx"}
TAG, IDS, MODE = sys.argv[1], sys.argv[2], sys.argv[3]
NW = int(sys.argv[4]) if len(sys.argv) > 4 else 8
MEMCAP = float(sys.argv[5]) if len(sys.argv) > 5 else 100.0
ALL = {j['id']: j for j in json.load(open(f'{W}/jobs_all.json'))}
ids = [l.strip() for l in open(IDS) if l.strip() and not l.startswith('#')]
lock = threading.Lock(); used = [0.0]; log = open(f'{W}/{TAG}.runlog', 'a')


def say(*a):
    with lock:
        log.write(time.strftime('%H:%M:%S ') + ' '.join(str(x) for x in a) + '\n'); log.flush()


def safe(s, n=60):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_")[:n] or "job"


def need_gb(j):
    mb = (j.get('model_bytes') or 0) >> 20
    for hi, gb in ((50, 4), (100, 8.2), (250, 16), (800, 24.8), (3000, 43.5)):
        if mb < hi:
            return gb
    return 45


def fetch(j):
    jid = j['id']; name = safe(j.get('name') or 'job') + '_' + jid[:6]
    jobdir = f'{W}/jobs/{name}'
    mark = jobdir + '/.fetched'
    if os.path.exists(mark):
        return jobdir
    body = s3.get_object(Bucket=B, Key=j['files_key'])['Body'].read()
    try:
        body = gzip.decompress(body)
    except OSError:
        pass
    mf = json.loads(body)
    items = []
    for f in mf:
        parts = [p.lower() if p.lower() in CANON else p for p in f['p'].replace('\\', '/').split('/') if p]
        items.append([f.get('key') or '', os.path.join(jobdir, *parts), f['size']])
    lst = f'{W}/tmp/{jid}.fetch.json'; os.makedirs(f'{W}/tmp', exist_ok=True); json.dump(items, open(lst, 'w'))
    r = subprocess.run(['/opt/conv/env/bin/python', f'{W}/fetch.py', lst, '24'], capture_output=True, text=True, timeout=7200)
    fr = json.loads(r.stdout.strip().splitlines()[-1])
    if fr.get('n_errors'):
        raise RuntimeError(f'fetch errors {fr.get("errors")}')
    open(mark, 'w').write(json.dumps(fr))
    return jobdir


def one(jid):
    j = ALL[jid]; g = need_gb(j) * (0.6 if MODE.startswith('ana:') else 1.0)
    while True:
        with lock:
            if used[0] + g <= MEMCAP or used[0] == 0:
                used[0] += g; break
        time.sleep(5)
    t = time.time()
    try:
        jobdir = fetch(j)
        od = f'{W}/out/{TAG}/{jid}'; os.makedirs(od, exist_ok=True)
        env = dict(os.environ, PYTHONUNBUFFERED='1', MPLBACKEND='Agg', WD_FAMS=','.join(j.get('fams') or []),
                   OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
        env.pop('LD_LIBRARY_PATH', None)
        if MODE.startswith('ana:'):
            dec = MODE[4:]
            cmd = [PY, '-u', f'{W}/wdump.py', dec, jobdir, f'{od}/{jid}.json']
        else:
            pipe = MODE[5:]
            name = os.path.basename(jobdir)
            cmd = [PY, '-u', f'{pipe}/decode/sds2_to_step.py', jobdir, '-o', f'{od}/{name}_stage2.step', '--stage', '2', '--verify']
        with open(f'{od}/run.log', 'w') as lf:
            rc = subprocess.run(['timeout', '10800'] + cmd, stdout=lf, stderr=subprocess.STDOUT, env=env, cwd=od).returncode
        say('done', jid, j.get('name'), 'rc', rc, 'sec', round(time.time() - t))
        if MODE.startswith('ana:'):
            if os.path.exists(f'{od}/{jid}.json'):
                s3.upload_file(f'{od}/{jid}.json', B, f'{RES}/{TAG}/{jid}.json')
        else:
            for fn in os.listdir(od):
                if fn.endswith(('_manifest.json', '_pieces.csv', '_skipped.csv', '.log', '_preview.png')):
                    s3.upload_file(f'{od}/{fn}', B, f'{RES}/{TAG}/{jid}/{fn}')
            s3.put_object(Bucket=B, Key=f'{RES}/{TAG}/{jid}/rc.json', Body=json.dumps(dict(rc=rc, sec=round(time.time() - t), name=j.get('name'),
                                                                                            step_bytes=sum(os.path.getsize(f'{od}/{x}') for x in os.listdir(od) if x.endswith('.step')))).encode())
        s3.upload_file(f'{od}/run.log', B, f'{RES}/{TAG}/{jid}.log')
    except Exception as e:
        say('error', jid, type(e).__name__, str(e)[:300])
        try:
            s3.put_object(Bucket=B, Key=f'{RES}/{TAG}/{jid}.err', Body=f'{type(e).__name__}: {e}'.encode())
        except Exception:
            pass
    finally:
        with lock:
            used[0] -= g


ids.sort(key=lambda i: (ALL[i].get('model_bytes') or 0) * (1 if MODE.startswith('ana:') else -1))
q = list(ids); qlock = threading.Lock()


def worker():
    while True:
        with qlock:
            if not q:
                return
            jid = q.pop(0)
        one(jid)


ts = [threading.Thread(target=worker) for _ in range(NW)]
[t.start() for t in ts]; [t.join() for t in ts]
s3.put_object(Bucket=B, Key=f'{RES}/{TAG}/_DONE', Body=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()).encode())
say('ALL DONE')
