"""box driver: run job specs in parallel subprocesses; each job downloads its inputs from S3 (instance role), runs one tool,
writes out/<name>.json (+ .log). Results are synced to s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/db1v2-eng/
usage: boxdrive.py jobs.json NPROC"""
import json, os, sys, subprocess, time, concurrent.futures as cf, boto3
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, 'out'); DATA = os.path.join(HERE, 'data')
os.makedirs(OUT, exist_ok=True); os.makedirs(DATA, exist_ok=True)
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
PY = os.path.join(HERE, 'venv/bin/python')
def fetch(key):
    if not key: return None
    loc = os.path.join(DATA, str(abs(hash(key)) % 10**12) + '_' + os.path.basename(key)[-60:].replace(' ', '_'))
    if not os.path.exists(loc):
        s3.download_file(B, key, loc + '.part'); os.rename(loc + '.part', loc)
    return loc
def run(job):
    name = job['name']; res = os.path.join(OUT, name + '.json')
    if os.path.exists(res): return name, 'cached'
    t = time.time()
    try:
        db1 = fetch(job.get('db1_key')); ifc = fetch(job.get('ifc_key'))
        cmd = [PY, os.path.join(HERE, job['tool'])] + [str(a).replace('{db1}', db1 or '').replace('{ifc}', ifc or '').replace('{out}', res) for a in job['args']]
        with open(os.path.join(OUT, name + '.log'), 'w') as lg:
            rc = subprocess.run(cmd, cwd=HERE, stdout=lg, stderr=subprocess.STDOUT, timeout=job.get('timeout', 14400)).returncode
        if not os.path.exists(res): json.dump({'name': name, 'rc': rc, 'error': 'no result'}, open(res, 'w'))
    except Exception as e:
        json.dump({'name': name, 'error': f'{type(e).__name__}: {str(e)[:300]}'}, open(res, 'w'))
    if job.get('cleanup', True):
        for k in ('db1_key', 'ifc_key'):
            pass
    return name, round(time.time() - t)
if __name__ == '__main__':
    jobs = json.load(open(sys.argv[1])); n = int(sys.argv[2])
    with cf.ProcessPoolExecutor(n) as ex:
        for name, r in ex.map(run, jobs):
            print(time.strftime('%H:%M:%S'), name, r, flush=True)
    print('ALLDONE', flush=True)
