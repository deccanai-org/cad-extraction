"""modal_restore.py - Modal app `pmp-complete-sds2ifc` (workspace navaneeth, volume pmp-out): the GREEN restoration
track for SDS/2 and IFC models of the partial tier (samples n3, n4, n5 of jobs/new5.jsonl).

  # SDS/2: run pinned converter builds on the job with read-only probes (bolt records, hole stacks, decoded holes)
  .venv/bin/modal run complete/sds2_ifc/modal_restore.py::probe --tag n5_sds2 --labels v4,v5.5.11
  # restorations (writes /<model_id>/complete/sds2_ifc/ on the volume and returns restoration_log.json)
  .venv/bin/modal run complete/sds2_ifc/modal_restore.py::restore --tags n3_ifc_approx,n4_ifc_c2s,n5_sds2

Inputs come only through the pre-signed GET URLs of jobs/urls/new5.signed.jsonl (never printed / stored). Outputs go
to the volume pmp-out under /<model_id>/complete/sds2_ifc/ only.
"""
import json, os, pathlib, sys, time

import modal

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent                       # partial_modal
APP_NAME = 'pmp-complete-sds2ifc'
VOL = '/vol'
TRACK = 'complete/sds2_ifc'

app = modal.App(APP_NAME)
vol = modal.Volume.from_name('pmp-out')


def _image():
    import importlib.util
    spec = importlib.util.spec_from_file_location('pmp_src_sds2_modal_image', str(ROOT / 'src_sds2' / 'modal_image.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    img = mod.build(modal, ROOT / 'src_sds2')
    return img.add_local_dir(str(HERE), '/pmp/sds2_ifc', ignore=['**/__pycache__/**', '*.pyc', 'out/**', 'work/**'])


image = _image() if (ROOT / 'src_sds2' / 'modal_image.py').exists() else modal.Image.debian_slim()


def _fetch(url, dest):
    import hashlib, urllib.request
    h = hashlib.sha256()
    n = 0
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'pmp-complete/1'}), timeout=180) as r, \
                    open(dest, 'wb') as f:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
                    h.update(b)
                    n += len(b)
            return dict(bytes=n, sha256=h.hexdigest())
        except Exception:  # noqa: BLE001
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))
            h, n = hashlib.sha256(), 0


def _sds2_job(urls, work, sds2_sha):
    """fetch + extract the SDS/2 job zip, link it under its root name; -> (job link path, root name, shipped STEP)"""
    import subprocess
    sys.path.insert(0, '/pmp/src_sds2')
    import stage as S
    os.makedirs(work, exist_ok=True)
    shipped = os.path.join(work, 'shipped.step')
    _fetch(urls['step'], shipped)
    jz = os.path.join(work, 'job.zip')
    info = _fetch(urls['source'], jz)
    assert not sds2_sha or info['sha256'] == sds2_sha, 'sds2 zip sha256 mismatch'
    jd = os.path.join(work, 'job')
    S.safe_extract(jz, jd)
    os.remove(jz)
    tops = sorted(x for x in os.listdir(jd) if not x.startswith('.'))
    root = S.root_name(shipped) or tops[0]
    ld = os.path.join(work, 'link')
    os.makedirs(ld, exist_ok=True)
    if not os.path.exists(os.path.join(ld, root)):
        os.symlink(os.path.join(jd, tops[0]), os.path.join(ld, root))
    return os.path.join(ld, root), root, shipped


def _conv_tree(label, work):
    sys.path.insert(0, '/pmp/src_sds2')
    import stage as S
    conv = json.load(open('/pmp/src_sds2/converters.json'))['labels'][label]
    zp = os.path.join(os.environ.get('PMP_SDS2_CONVERTERS', '/opt/sds2_converters'), conv['zip'])
    cd = os.path.join(work, 'conv_' + label)
    if not os.path.exists(cd):
        S.safe_extract(zp, cd)
    return os.path.join(cd, 'sds2-step-pipeline'), conv


@app.function(image=image, volumes={VOL: vol}, cpu=4.0, memory=16384, timeout=4 * 3600, max_containers=6)
def probe_sds2(model_id: str, urls: dict, sds2_sha: str, label: str) -> dict:
    import subprocess, shutil
    work = f'/tmp/w/{model_id[:16]}'
    job, root, shipped = _sds2_job(urls, work, sds2_sha)
    conv_root, conv = _conv_tree(label, work)
    out = os.path.join(work, 'probe_' + label)
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    with open(os.path.join(out, 'probe.log'), 'w') as lf:
        rc = subprocess.call(['/opt/conv/bin/python', '-u', '/pmp/sds2_ifc/sds2_probe.py', conv_root, job, out],
                             stdout=lf, stderr=subprocess.STDOUT, cwd=out, env=dict(os.environ, MPLBACKEND='Agg'))
    dst = f'{VOL}/{model_id}/complete/sds2_ifc/probe_{label}'
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(out, dst)
    shutil.copy(shipped, f'{VOL}/{model_id}/complete/sds2_ifc/shipped.step') if not os.path.exists(
        f'{VOL}/{model_id}/complete/sds2_ifc/shipped.step') else None
    vol.commit()
    tail = open(os.path.join(out, 'probe.log')).read()[-3000:]
    return dict(model_id=model_id, label=label, rc=rc, seconds=round(time.time() - t0, 1), root=root,
                files=sorted(os.listdir(out)), log_tail=tail)


def _rows(tags):
    rows = {}
    for ln in open(ROOT / 'jobs' / 'urls' / 'new5.signed.jsonl'):
        j = json.loads(ln)
        if j['tag'] in tags:
            rows[j['tag']] = j
    return rows


@app.local_entrypoint()
def probe(tag: str = 'n5_sds2', labels: str = 'v4,v5.5.11'):
    j = _rows([tag])[tag]
    urls = {k: j['urls'][k] for k in ('step', 'source')}
    calls = [probe_sds2.spawn(j['model_id'], urls, j['source'].get('sha256'), lb) for lb in labels.split(',')]
    for c in calls:
        r = c.get()
        print(json.dumps({k: v for k, v in r.items() if k != 'log_tail'}))
        print(r['log_tail'][-1500:])


@app.function(image=image, volumes={VOL: vol}, cpu=8.0, memory=32768, timeout=4 * 3600, max_containers=6)
def restore_model(tag: str, model_id: str, kind: str, urls: dict, meta: dict) -> dict:
    """run the restoration for one model in the pipeline env (/opt/pipe: python 3.11, ifcopenshell, OCP, build123d)"""
    import subprocess, shutil
    work = f'/tmp/r/{model_id[:16]}'
    os.makedirs(work, exist_ok=True)
    out = os.path.join(work, 'out')
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    vdir = f'{VOL}/{model_id}/complete/sds2_ifc'
    os.makedirs(vdir, exist_ok=True)
    shipped = os.path.join(work, 'shipped.step')
    _fetch(urls['step'], shipped)
    args = []
    if kind == 'ifc':
        ifc = os.path.join(work, 'source.ifc')
        _fetch(urls['source'], ifc)
        for k in ('parts_json', 'src_parts', 'step_parts'):
            if urls.get('detail/' + k):
                _fetch(urls['detail/' + k], os.path.join(work, k + ('.json' if k == 'parts_json' else '.jsonl.gz')))
        cmd = ['/opt/pipe/bin/python', '-u', '/pmp/sds2_ifc/restore_ifc.py', '--ifc', ifc, '--step', shipped,
               '--detail', work, '--out', out, '--model-id', model_id, '--tag', tag]
    else:
        cmd = ['/opt/pipe/bin/python', '-u', '/pmp/sds2_ifc/restore_sds2.py', '--probe-dir', vdir, '--step', shipped,
               '--facts', f'{VOL}/{model_id}/source/sds2_facts.json', '--out', out, '--model-id', model_id, '--tag', tag]
    cmd += ['--meta', json.dumps(meta)]
    with open(os.path.join(out, 'restore.log'), 'w') as lf:
        rc = subprocess.call(cmd, stdout=lf, stderr=subprocess.STDOUT, cwd=work)
    for f in os.listdir(out):
        p = os.path.join(out, f)
        (shutil.copytree(p, os.path.join(vdir, f), dirs_exist_ok=True) if os.path.isdir(p) else shutil.copy(p, os.path.join(vdir, f)))
    vol.commit()
    log = {}
    lp = os.path.join(out, 'restoration_log.json')
    if os.path.exists(lp):
        log = json.load(open(lp))
    return dict(tag=tag, model_id=model_id, rc=rc, seconds=round(time.time() - t0, 1), files=sorted(os.listdir(out)),
                summary=log.get('summary'), outputs=log.get('outputs'),
                log_sha256=(__import__('hashlib').sha256(open(lp, 'rb').read()).hexdigest() if os.path.exists(lp) else None),
                log_tail=open(os.path.join(out, 'restore.log')).read()[-4000:])


@app.local_entrypoint()
def restore(tags: str = 'n3_ifc_approx,n4_ifc_c2s,n5_sds2', out: str = ''):
    rows = _rows(tags.split(','))
    calls = []
    for tag, j in rows.items():
        kind = 'ifc' if j['step_source'] == 'ifc' else 'sds2'
        urls = {k: v for k, v in j['urls'].items() if k in ('step', 'source') or k.startswith('detail/')}
        meta = dict(pid=j['pid'], model_folder=j['model_folder'], relpath=j['relpath'], partial=j.get('partial'))
        calls.append(restore_model.spawn(tag, j['model_id'], kind, urls, meta))
    res = []
    for c in calls:
        r = c.get()
        res.append(r)
        print(json.dumps({k: v for k, v in r.items() if k != 'log_tail'}, indent=1))
        print(r['log_tail'][-2500:])
    if out:
        json.dump(res, open(out, 'w'), indent=1)


@app.function(image=image, volumes={VOL: vol}, cpu=4.0, memory=16384, timeout=2 * 3600, max_containers=6)
def pipe_script(script: str, args: list, urls: dict, model_id: str) -> dict:
    """run one of this track's scripts in the pipeline env with the model's inputs fetched to /tmp/d/ (diagnostics)"""
    import subprocess
    work = f'/tmp/d/{model_id[:16]}'
    os.makedirs(work, exist_ok=True)
    for k, v in urls.items():
        dest = os.path.join(work, k.replace('/', '_'))
        if not os.path.exists(dest):
            _fetch(v, dest)
    p = subprocess.run(['/opt/pipe/bin/python', '-u', f'/pmp/sds2_ifc/{script}'] + [a.replace('{W}', work).replace('{V}', f'{VOL}/{model_id}') for a in args],
                       capture_output=True, text=True, cwd=work)
    vol.commit()
    return dict(rc=p.returncode, out=p.stdout[-20000:], err=p.stderr[-5000:])


@app.local_entrypoint()
def diag(tag: str, script: str, args: str = '', keys: str = 'step,source'):
    j = _rows([tag])[tag]
    urls = {k: j['urls'][k] for k in keys.split(',') if k in j['urls']}
    r = pipe_script.remote(script, args.split() if args else [], urls, j['model_id'])
    print('rc', r['rc'])
    print(r['out'])
    print(r['err'])
