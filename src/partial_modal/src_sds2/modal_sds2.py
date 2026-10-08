"""pmp-src-sds2: the SDS/2 -> IFC source stage on Modal (workspace navaneeth; app and volume names start with pmp-).

Image (sds2_image()):
  debian slim + the system libs OCC needs (libgl1 libxrender1 libxext6 libsm6 libfontconfig1 libxkbcommon0 libxi6)
  /opt/conv   python 3.12 venv with the converters' pinned pip set (env/conv_requirements.txt) - every sds2-step-pipeline
              build v4 .. v5.5.11 names the same set; pip freeze -> /opt/conv_freeze.txt
  /opt/pipe   python 3.11 venv (uv-managed interpreter) with the fleet's pinned pipeline requirements
              (env/pipe_requirements.txt) for the reproduction proof; uv pip freeze -> /opt/pipe_freeze.txt
  /opt/sds2_converters   the 18 converter zips the partial tier uses, sha256-checked at build (SHA256SUMS) and again
              per run against the model's pin (converters.json)
  /pmp/src_sds2          this component's code (stage.py, pin.py, facts_build.py, emitter/, proofkit/)
No credentials of any kind: inputs arrive as pre-signed GET URLs inside the job dict.

Function sds2_source(job, cls=None, budget_s=None) -> result dict (stage.run's, URL-free):
  runs stage.run in a container, publishes the stage's outputs to the Volume pmp-out:
     /<model_id>/source/                 on success: model.ifc, provenance.json, sds2_facts.json, reproduction.csv.gz,
                                         converter/ (replaced atomically: written to source.tmp, then renamed)
     /<model_id>/logs/src_sds2.log       stage log (appended per attempt)
     /<model_id>/logs/src_sds2_result.json
     /<model_id>/logs/src_sds2_failed/   on failure: provenance.json (ok false + evidence) + converter/ logs
  Resources per size class (delivered STEP bytes): RES below, applied with .with_options() by call_for_class().
  Retries: only container-level failures (preemption / OOM kill) are retried by Modal (1 retry); a stage failure is a
  returned result with ok false and its verdict, never retried silently.

Other apps can use it in two ways:
  - deploy:  .venv/bin/modal deploy src_sds2/modal_sds2.py, then
             modal.Function.from_name('pmp-src-sds2', 'sds2_source').with_options(**res).remote(job)
  - plug-in: build an image with sds2_image() and call /pmp/src_sds2/stage.py run(job, ctx) inside it

Unit test (new sample n5 only):
  .venv/bin/modal run src_sds2/modal_sds2.py --job-file <job.json with GET URLs> --result-file <out.json>
"""
import json, os, shutil, time

import modal

HERE = os.path.dirname(os.path.abspath(__file__))
APP_NAME = 'pmp-src-sds2'
VOLUME_NAME = 'pmp-out'
UV_VERSION = '0.12.14'
SYSTEM_LIBS = ['libgl1', 'libxrender1', 'libxext6', 'libsm6', 'libfontconfig1', 'libxkbcommon0', 'libxi6']

# size class -> Modal resources. The converter is single-threaded (fleet: 290 s / 2.3 GB peak for a 186 MB STEP); the
# proof's IfcOpenShell pass and the OpenCASCADE measuring use J worker processes.
RES = {
    'S':  dict(cpu=2.0,  memory=8 * 1024,  timeout=2 * 3600,  J=4),
    'M':  dict(cpu=4.0,  memory=16 * 1024, timeout=4 * 3600,  J=8),
    'L':  dict(cpu=8.0,  memory=32 * 1024, timeout=8 * 3600,  J=16),
    'XL': dict(cpu=16.0, memory=64 * 1024, timeout=16 * 3600, J=32),
}


def size_class(nbytes):
    b = int(nbytes or 0)
    return 'S' if b < 10**7 else 'M' if b < 10**8 else 'L' if b < 5 * 10**8 else 'XL' if b < 10**9 else 'XXL'


CONV_PINS = ['cadquery-ocp==8.0.1.0.0', 'numpy==2.5.3', 'scipy==1.18.1', 'shapely==2.1.2', 'matplotlib==3.11.2']


def sds2_image():
    conv_req = list(CONV_PINS)               # = env/conv_requirements.txt (checked when the file is here, i.e. locally)
    rp = os.path.join(HERE, 'env', 'conv_requirements.txt')
    if os.path.exists(rp):
        assert conv_req == [ln.strip() for ln in open(rp) if ln.strip() and not ln.startswith('#')], \
            'CONV_PINS differs from env/conv_requirements.txt'
    return (
        modal.Image.debian_slim(python_version='3.12')
        .apt_install(*SYSTEM_LIBS)
        .run_commands(
            'python -m venv /opt/conv',
            '/opt/conv/bin/pip install --no-cache-dir ' + ' '.join(conv_req),
            '/opt/conv/bin/pip freeze > /opt/conv_freeze.txt',
            '/opt/conv/bin/python -c "import OCP, numpy, scipy, shapely, matplotlib; '
            'from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox; assert BRepPrimAPI_MakeBox(1, 2, 3).Shape() is not None; '
            'print(\'conv env ok numpy\', numpy.__version__)"')
        .add_local_file(os.path.join(HERE, 'env', 'pipe_requirements.txt'), '/opt/pipe_requirements.txt', copy=True)
        .run_commands(
            f'pip install --no-cache-dir uv=={UV_VERSION}',
            'UV_PYTHON_INSTALL_DIR=/opt/uvpython uv venv --python 3.11 /opt/pipe',
            'uv pip install --no-cache --python /opt/pipe/bin/python -r /opt/pipe_requirements.txt',
            'uv pip freeze --python /opt/pipe/bin/python > /opt/pipe_freeze.txt',
            '/opt/pipe/bin/python -c "import build123d, ifcopenshell, OCP, numpy; print(\'pipe env ok ifcopenshell\', '
            'ifcopenshell.version)"')
        .add_local_dir(os.path.join(HERE, 'converters'), '/opt/sds2_converters', copy=True)
        .run_commands('cd /opt/sds2_converters && sha256sum -c SHA256SUMS')
        .env({'PMP_SDS2_CONVERTERS': '/opt/sds2_converters', 'PMP_CONV_PY': '/opt/conv/bin/python',
              'PMP_PIPE_PY': '/opt/pipe/bin/python'})
        .add_local_dir(HERE, '/pmp/src_sds2', ignore=['converters', 'converters/**', 'tests/out', 'tests/out/**',
                                                       '**/__pycache__', '**/__pycache__/**', '*.pyc', '**/*.pyc'])
    )


app = modal.App(APP_NAME)
image = sds2_image()
vol = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)


def _publish(src, dst):
    tmp, old = dst.rstrip('/') + '.tmp', dst.rstrip('/') + '.old'
    for p in (tmp, old):
        shutil.rmtree(p, ignore_errors=True)
    shutil.copytree(src, tmp)
    if os.path.exists(dst):
        os.rename(dst, old)
    os.rename(tmp, dst)
    shutil.rmtree(old, ignore_errors=True)


@app.function(image=image, volumes={'/vol': vol}, cpu=RES['M']['cpu'], memory=RES['M']['memory'],
              timeout=RES['M']['timeout'], retries=modal.Retries(max_retries=1, initial_delay=10.0, backoff_coefficient=2.0),
              max_containers=10)
def sds2_source(job: dict, cls: str = None, budget_s: int = None) -> dict:
    import sys
    sys.path.insert(0, '/pmp/src_sds2')
    import stage
    t0 = time.time()
    mid = job.get('id') or job.get('model_id')
    cls = cls or job.get('cls') or size_class(job.get('bytes'))
    res = RES.get(cls, RES['M'])
    budget = int(budget_s or res['timeout'])
    jd = os.path.join('/tmp/pmp', (mid or 'noid')[:24] + '.src_sds2')
    shutil.rmtree(jd, ignore_errors=True)
    work, out = os.path.join(jd, 'work'), os.path.join(jd, 'out')
    os.makedirs(work)
    os.makedirs(out)
    MD = os.path.join('/vol', mid or 'noid')
    os.makedirs(os.path.join(MD, 'logs'), exist_ok=True)
    logp = os.path.join(MD, 'logs', 'src_sds2.log')

    def log(msg):
        line = time.strftime('%Y-%m-%dT%H:%M:%SZ ', time.gmtime()) + str(msg)
        with open(logp, 'a') as f:
            f.write(line + '\n')
        print(line, flush=True)
    log(f'start src_sds2 {mid} cls {cls} cpu {res["cpu"]} mem {res["memory"]} MiB budget {budget}s '
        f'task {os.environ.get("MODAL_TASK_ID")}')
    ctx = dict(stage='src_sds2', work=work, out=out, log=log, J=res['J'], cls=cls, deadline=t0 + budget - 600)
    rec = stage.run(job, ctx)
    rec['cls'] = cls
    rec['container'] = dict(task_id=os.environ.get('MODAL_TASK_ID'), image_id=os.environ.get('MODAL_IMAGE_ID'),
                            region=os.environ.get('MODAL_REGION'), cloud=os.environ.get('MODAL_CLOUD_PROVIDER'),
                            nproc=os.cpu_count(), cpu=res['cpu'], memory_mib=res['memory'])
    try:
        import resource
        rec['container']['peak_rss_children_gib'] = round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 2**20, 2)
    except Exception:
        pass
    if rec['ok']:
        _publish(out, os.path.join(MD, 'source'))
        rec['volume_dir'] = f'/{mid}/source'
    else:
        _publish(out, os.path.join(MD, 'logs', 'src_sds2_failed'))
        rec['volume_dir'] = f'/{mid}/logs/src_sds2_failed'
    rec['wall_seconds'] = round(time.time() - t0, 1)
    with open(os.path.join(MD, 'logs', 'src_sds2_result.json'), 'w') as f:
        json.dump(rec, f, indent=1, default=str)
    log(f'done ok={rec["ok"]} verdict={rec["verdict"]} error={rec["error"]} {rec["wall_seconds"]}s')
    shutil.rmtree(jd, ignore_errors=True)
    vol.commit()
    return rec


def call_for_class(fn, job, cls=None):
    """fn = sds2_source (in this app) or modal.Function.from_name('pmp-src-sds2', 'sds2_source'): run one job with
    its size class's resources. Returns the result dict; a >= 1 GB model is refused as too_big_v1 without a call."""
    cls = cls or job.get('cls') or size_class(job.get('bytes'))
    if cls not in RES:
        return dict(ok=False, verdict='too_big_v1', error=f'size class {cls} is out of scope for v1', cls=cls,
                    model_id=job.get('id') or job.get('model_id'))
    r = RES[cls]
    return fn.with_options(cpu=r['cpu'], memory=r['memory'], timeout=r['timeout']).remote(job, cls, r['timeout'])


@app.local_entrypoint()
def main(job_file: str, result_file: str = '', cls: str = ''):
    with open(job_file) as f:
        txt = f.read().strip()
    job = json.loads(txt.splitlines()[0]) if txt.startswith('{') and '\n{' in txt else json.loads(txt)
    t0 = time.time()
    rec = call_for_class(sds2_source, job, cls or None)
    rec['client_wall_seconds'] = round(time.time() - t0, 1)
    s = json.dumps(rec, indent=1, default=str)
    if result_file:
        with open(result_file, 'w') as f:
            f.write(s)
    print(s[:6000])
