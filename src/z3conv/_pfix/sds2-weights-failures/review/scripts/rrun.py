#!/usr/bin/env python3
"""Reviewer runner (sds2-weights-failures-review): fetch SDS2 job folders with the fleet's layout rules and run the fleet
command (sds2_to_step.py JOB -o X_stage2.step --stage 2 --verify) with a given pipeline tree.
usage: rrun.py TAG IDS_FILE TREE_DIR [WORKERS] [MEMCAP_GB] [JOBDIR_SUFFIX]"""
import os, sys, json, gzip, time, subprocess, threading, re
import boto3
from botocore.config import Config
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=64, retries={'max_attempts': 20, 'mode': 'standard'}))
B = 'bim-proprietary-data'
W = '/work/agentwork/sds2-weights-failures-review'
RES = 'cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-weights-failures-review'
PY = f'{W}/env/bin/python'
CANON = {"main", "mem", "subm", "jsetup", "job_mtrl", "mem_idx", "subm_idx"}
TAG, IDS, TREE = sys.argv[1], sys.argv[2], sys.argv[3]
NW = int(sys.argv[4]) if len(sys.argv) > 4 else 6
MEMCAP = float(sys.argv[5]) if len(sys.argv) > 5 else 90.0
ALL = {}
for nm in ('jobs.json', 'jobs_merged.json', 'jobs_reconvert.json'):
    p = f'{W}/full_{nm}'
    if not os.path.exists(p):
        try:
            open(p, 'wb').write(s3.get_object(Bucket=B, Key='cad-disk-extract/zenitude-data-3/_state/conv/sds2/' + nm)['Body'].read())
        except Exception:
            continue
    d = json.load(open(p)); d = d.get('jobs', list(d.values())) if isinstance(d, dict) else d
    for j in d:
        if isinstance(j, dict) and j.get('id') and j.get('files_key'):
            try: j['model_bytes'] = int(j.get('model_bytes') or j.get('size') or 0)
            except (TypeError, ValueError): j['model_bytes'] = 0
            ALL.setdefault(j['id'], j)
ids = [l.strip() for l in open(IDS) if l.strip() and not l.startswith('#')]
for i in [i for i in ids if i not in ALL]:
    try:
        r = json.loads(s3.get_object(Bucket=B, Key=f'cad-disk-extract/zenitude-data-3/_state/conv/sds2/results/{i}.json')['Body'].read())
        fk = f"cad-disk-extract/zenitude-data-3/_state/conv/sds2/files/{r.get('fpc') or i}.json.gz"
        ALL[i] = dict(id=i, name=r.get('name'), files_key=fk, model_bytes=int(r.get('model_bytes') or 0))
        s3.head_object(Bucket=B, Key=ALL[i]['files_key'])
    except Exception as e:
        ALL.pop(i, None); print('unknown job id', i, e)
ids = [i for i in ids if i in ALL]
lock = threading.Lock(); used = [0.0]; flock = {}
os.makedirs(f'{W}/logs', exist_ok=True); log = open(f'{W}/logs/{TAG}.runlog', 'a')
def say(*a):
    with lock:
        log.write(time.strftime('%H:%M:%S ') + ' '.join(str(x) for x in a) + '\n'); log.flush()
def safe(s, n=60):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_")[:n] or "job"
def need_gb(j):
    mb = (j.get('model_bytes') or 0) >> 20
    for hi, gb in ((50, 4), (100, 8), (250, 16), (800, 25), (3000, 44)):
        if mb < hi: return gb
    return 45
def fetch(j):
    jid = j['id']; name = safe(j.get('name') or 'job') + '_' + jid[:6]
    jobdir = f'{W}/jobs/{name}'; mark = jobdir + '/.fetched'
    with lock:
        lk = flock.setdefault(jid, threading.Lock())
    with lk:
        if os.path.exists(mark): return jobdir
        body = s3.get_object(Bucket=B, Key=j['files_key'])['Body'].read()
        try: body = gzip.decompress(body)
        except OSError: pass
        items = []
        for f in json.loads(body):
            parts = [p.lower() if p.lower() in CANON else p for p in f['p'].replace('\\', '/').split('/') if p]
            items.append([f.get('key') or '', os.path.join(jobdir, *parts), f['size']])
        lst = f'{W}/tmp/{jid}.fetch.json'; os.makedirs(f'{W}/tmp', exist_ok=True); json.dump(items, open(lst, 'w'))
        r = subprocess.run(['/opt/conv/env/bin/python', f'{W}/fetch.py', lst, '16'], capture_output=True, text=True, timeout=7200)
        fr = json.loads(r.stdout.strip().splitlines()[-1])
        if fr.get('n_errors'): raise RuntimeError(f'fetch errors {fr.get("errors")}')
        open(mark, 'w').write(json.dumps(fr))
    return jobdir
def one(jid):
    j = ALL[jid]; g = need_gb(j)
    while True:
        with lock:
            if used[0] + g <= MEMCAP or used[0] == 0:
                used[0] += g; break
        time.sleep(5)
    t = time.time()
    try:
        jobdir = fetch(j)
        if len(sys.argv) > 6 and sys.argv[6]:
            jobdir = jobdir + sys.argv[6]          # e.g. a prepared variant folder (subm_idx hidden)
        od = f'{W}/out/{TAG}/{jid}'; os.makedirs(od, exist_ok=True)
        env = dict(os.environ, PYTHONUNBUFFERED='1', MPLBACKEND='Agg', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
        env.pop('LD_LIBRARY_PATH', None)
        name = os.path.basename(jobdir)
        cmd = [PY, '-u', f'{TREE}/decode/sds2_to_step.py', jobdir, '-o', f'{od}/{name}_stage2.step', '--stage', '2', '--verify']
        with open(f'{od}/run.log', 'w') as lf:
            rc = subprocess.run(['timeout', '10800'] + cmd, stdout=lf, stderr=subprocess.STDOUT, env=env, cwd=od).returncode
        sec = round(time.time() - t)
        say('done', jid, j.get('name'), 'rc', rc, 'sec', sec)
        for fn in os.listdir(od):
            if fn.endswith(('_manifest.json', '_pieces.csv', '_skipped.csv', '.log')):
                s3.upload_file(f'{od}/{fn}', B, f'{RES}/{TAG}/{jid}/{fn}')
        s3.put_object(Bucket=B, Key=f'{RES}/{TAG}/{jid}/rc.json', Body=json.dumps(dict(rc=rc, sec=sec, name=j.get('name'), tree=TREE,
            step_bytes=sum(os.path.getsize(f'{od}/{x}') for x in os.listdir(od) if x.endswith('.step')))).encode())
    except Exception as e:
        say('error', jid, type(e).__name__, str(e)[:300])
        try: s3.put_object(Bucket=B, Key=f'{RES}/{TAG}/{jid}.err', Body=f'{type(e).__name__}: {e}'.encode())
        except Exception: pass
    finally:
        with lock: used[0] -= g
from concurrent.futures import ThreadPoolExecutor
say('start', TAG, len(ids), TREE)
with ThreadPoolExecutor(NW) as ex:
    list(ex.map(one, ids))
say('ALLDONE', TAG)
s3.put_object(Bucket=B, Key=f'{RES}/{TAG}/DONE', Body=time.strftime('%FT%TZ').encode())
