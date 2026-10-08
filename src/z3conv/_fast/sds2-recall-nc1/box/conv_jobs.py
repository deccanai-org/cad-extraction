#!/usr/bin/env python3
"""Convert selected data-3 SDS2 jobs with the official converter builds where the fleet has no STEP of that label, so
that v4c and v5.3 can be compared on every job with NC1 / IFC ground truth (agent box only).

  v4c  = sds2-step-pipeline-v4-candidate.zip  sha256 c5b65d27... (the data-4 / Disk-2 run-2 build)
  v5.3 = sds2-step-pipeline-v5.3.zip          sha256 81ca1f95... (the fleet's current build)
Same CLI as the fleet: decode/sds2_to_step.py <job> -o <name>_stage2.step --stage 2 --verify. Job files are fetched from
the data-3 files list (_state/conv/sds2/files/<fpc>.json.gz, keys resolved by the scan). Outputs go to
s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-recall-nc1/conv/<id>/<label>/ (never to
the fleet's conversions/ prefix); the STEP is indexed at once (stepidx cache keyed by its S3 key) and deleted locally.
usage: conv_jobs.py todo.json [--slots 6] [--timeout 5400]     todo = [[job id, label], ...]
"""
import os, sys, json, gzip, time, re, subprocess, hashlib, pickle, shutil, argparse, traceback, collections
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
B = 'bim-proprietary-data'
D3 = 'cad-disk-extract/zenitude-data-3'
RES = f'{D3}/_state/agentwork/sds2-recall-nc1'
W = os.environ.get('W', '/work/agentwork/sds2-recall-nc1')
PY = os.path.join(W, 'sds2env', 'bin', 'python')
SHA = {'v4c': 'c5b65d271d3a6c69853d745d705cbb92b431e8891686068e7a555e720b3c15f0',
       'v5.3': '81ca1f95dbb3bb2e115574045e4cd0e20a8ff067242655f1d1c7eb59ca8d9822'}
ZIP = {'v4c': 'sds2-step-pipeline-v4-candidate.zip', 'v5.3': 'sds2-step-pipeline-v5.3.zip'}
CANON = {"main", "mem", "subm", "jsetup", "job_mtrl", "mem_idx", "subm_idx"}
CACHE = os.path.join(W, 'cache'); os.makedirs(CACHE, exist_ok=True)
_c = {}


def s3():
    if 'c' not in _c:
        _c['c'] = boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 20, 'mode': 'standard'}, max_pool_connections=64))
    return _c['c']


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def safe(s, n=60):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_")[:n] or "job"


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''):
            h.update(b)
    return h.hexdigest()


def check_builds():
    for lab in SHA:
        z = os.path.join(W, ZIP[lab])
        if sha256_file(z) != SHA[lab]:
            raise SystemExit(f'{z}: sha256 mismatch')
        if not os.path.exists(os.path.join(W, 'conv', lab, 'sds2-step-pipeline', 'decode', 'sds2_to_step.py')):
            raise SystemExit(f'{lab} build not unpacked')


def fetch(row, jobdir):
    body = s3().get_object(Bucket=B, Key=row['files_key'])['Body'].read()
    mf = json.loads(gzip.decompress(body))
    miss = [f for f in mf if not f.get('key') and f['size'] > 0]
    if miss:
        return {'error': f'{len(miss)} model files without a stored copy'}

    def one(f):
        parts = [p.lower() if p.lower() in CANON else p for p in f['p'].replace('\\', '/').split('/') if p]
        path = os.path.join(jobdir, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not f.get('key'):
            open(path, 'wb').close(); return 0
        for i in range(5):
            try:
                if f['size'] < (64 << 20):
                    b = s3().get_object(Bucket=B, Key=f['key'])['Body'].read()
                    open(path, 'wb').write(b)
                else:
                    s3().download_file(B, f['key'], path)
                if os.path.getsize(path) != f['size']:
                    raise IOError('size')
                return f['size']
            except Exception:
                if i == 4:
                    raise
                time.sleep(1 + 2 * i)
    t0 = time.time()
    with ThreadPoolExecutor(32) as ex:
        nb = sum(ex.map(one, mf))
    return {'files': len(mf), 'bytes': nb, 'sec': round(time.time() - t0, 1)}


def convert(jid, lab, row, timeout):
    import stepidx
    name = safe(row.get('name') or (row.get('paths') or ['job'])[0].split(' :: ')[-1].rstrip('/').split('/')[-1]) + '_' + jid[:6]
    base = os.path.join(W, 'convwork', f'{jid}_{lab}')
    shutil.rmtree(base, ignore_errors=True)
    jobdir = os.path.join(base, 'job', name); outdir = os.path.join(base, 'out'); os.makedirs(outdir, exist_ok=True)
    rec = {'id': jid, 'label': lab, 'name': name, 'build_sha256': SHA[lab], 'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    try:
        fr = fetch(row, jobdir); rec['fetch'] = fr
        if fr.get('error'):
            rec['status'] = 'fetch_error'; return rec
        env = dict(os.environ, PYTHONUNBUFFERED='1', MPLBACKEND='Agg', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
        ex = os.path.join(W, 'sds2env', 'lib', 'libexpat.so.1')
        if os.path.exists(ex):
            env['LD_PRELOAD'] = ex
        step = os.path.join(outdir, f'{name}_stage2.step')
        cmd = ['timeout', '-k', '60', str(timeout), PY, '-u', os.path.join(W, 'conv', lab, 'sds2-step-pipeline', 'decode', 'sds2_to_step.py'),
               os.path.join(base, 'job', name), '-o', step, '--stage', '2', '--verify']
        t0 = time.time()
        with open(os.path.join(outdir, f'{name}_stage2.log'), 'w') as lf:
            rc = subprocess.run(cmd, cwd=outdir, env=env, stdout=lf, stderr=subprocess.STDOUT).returncode
        rec['rc'] = rc; rec['wall_s'] = round(time.time() - t0)
        shutil.rmtree(os.path.join(base, 'job'), ignore_errors=True)
        txt = open(os.path.join(outdir, f'{name}_stage2.log'), errors='replace').read()
        m = re.search(r'BRep valid: *(\d+)', txt); rec['brep_valid'] = int(m.group(1)) if m else None
        m = re.search(r'solids: (\{.*?\})', txt); rec['solids_line'] = m.group(1)[:400] if m else None
        pre = f'{RES}/conv/{jid}/{lab}/'
        for fn in sorted(os.listdir(outdir)):
            s3().upload_file(os.path.join(outdir, fn), B, pre + fn)
        if rc == 0 and os.path.exists(step) and os.path.getsize(step) > 0:
            key = pre + os.path.basename(step)
            ix = stepidx.index_step(step, log=log)
            ix['step_bytes'] = os.path.getsize(step)
            cp = os.path.join(CACHE, 'step_' + hashlib.sha1(key.encode()).hexdigest()[:16] + '.pkl')
            pickle.dump(ix, open(cp + '.tmp', 'wb'), protocol=4); os.replace(cp + '.tmp', cp)
            rec.update(status='ok', step=key, step_bytes=os.path.getsize(step),
                       manifest=(pre + f'{name}_stage2_manifest.json') if os.path.exists(os.path.join(outdir, f'{name}_stage2_manifest.json')) else None)
        else:
            rec['status'] = 'timeout' if rc in (124, 137) else 'failed'
            rec['log_tail'] = txt[-800:]
    except Exception as e:
        rec['status'] = 'error'; rec['error'] = traceback.format_exc()[-1200:]
    finally:
        shutil.rmtree(base, ignore_errors=True)
    rec['finished'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    p = os.path.join(W, 'convres', f'{jid}_{lab}.json'); os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(rec, open(p, 'w'), indent=1)
    s3().upload_file(p, B, f'{RES}/conv/{jid}/{lab}/result.json')
    return rec


def agent_steps():
    """inv/agent_steps.json: {id: {label: step entry}} for every successful conversion of this agent"""
    out = collections.defaultdict(dict)
    d = os.path.join(W, 'convres')
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        r = json.load(open(os.path.join(d, fn)))
        if r.get('status') == 'ok':
            out[r['id']][r['label']] = {'step': r['step'], 'stage': 2, 'step_size': r.get('step_bytes'), 'manifest': r.get('manifest'),
                                        'source': 'agent_run', 'build_sha256': r.get('build_sha256')}
    p = os.path.join(W, 'inv', 'agent_steps.json')
    json.dump(out, open(p + '.tmp', 'w'), indent=1); os.replace(p + '.tmp', p)
    s3().upload_file(p, B, f'{RES}/inv/agent_steps.json')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('todo'); ap.add_argument('--slots', type=int, default=6); ap.add_argument('--timeout', type=int, default=5400)
    a = ap.parse_args()
    check_builds()
    rows = {}
    for l in gzip.open(os.path.join(W, 'inv', 'contents_sds2.jsonl.gz'), 'rt'):
        r = json.loads(l); rows[r['id']] = r
    todo = [t for t in json.load(open(a.todo)) if not os.path.exists(os.path.join(W, 'convres', f'{t[0]}_{t[1]}.json'))]
    todo.sort(key=lambda t: rows[t[0]].get('model_bytes') or 0)
    log(f'{len(todo)} conversions, {a.slots} slots')
    with ThreadPoolExecutor(a.slots) as ex:
        for rec in ex.map(lambda t: convert(t[0], t[1], rows[t[0]], a.timeout), todo):
            log('conv', rec['id'][:8], rec['label'], rec.get('status'), rec.get('rc'), rec.get('wall_s'), rec.get('step_bytes'), rec.get('error', '')[-200:])
            agent_steps()


if __name__ == '__main__':
    main()
