"""pmp - partial-tier parametric pipeline on Modal (workspace "navaneeth", app "pmp-partial", volume "pmp-out").

Per model:  source (src_db1 / src_sds2 plug-in, or the package IFC)  ->  pipeline (job.py's steps)  ->  issues
(make_issues + the scripts/ tree + the SHIPPED build_issues_model.py run from that tree + its e2e checks + the bundle)
->  bundle upload (pre-signed PUT URL)  ->  index row.  See docs/README.md.

  # what the image holds / environment check (no model)
  .venv/bin/modal run app/modal_app.py::check_image
  # unit test of the pipeline stage on ONE new sample (job row with pre-signed GET URLs)
  .venv/bin/modal run app/modal_app.py::unit_pipeline --jobs JOBS_WITH_URLS.jsonl --tag n4_ifc_c2s
  # end to end for a job list (new5 only, unless --scale), <= --max-containers containers at once
  PMP_WITH_PLUGINS=1 .venv/bin/modal run app/modal_app.py::main --jobs JOBS_WITH_URLS.jsonl --run RUN --put-urls PRESIGN.json
  # re-upload bundles already on the volume with fresh PUT URLs; merge the index of a run
  .venv/bin/modal run app/modal_app.py::upload --run RUN --put-urls PRESIGN.json
  .venv/bin/modal run app/modal_app.py::collect --run RUN

No AWS credentials on Modal: inputs come through pre-signed GET URLs in the job rows, bundles leave through
pre-signed PUT URLs. Pre-signed URLs are never logged or written to the volume / index.
"""
import gzip, importlib.util, json, os, pathlib, re, sys, time

import modal

HERE = pathlib.Path(__file__).resolve().parent          # partial_modal/app
ROOT = HERE.parent                                      # partial_modal
REMOTE_APP = '/pmp/app'
sys.path.insert(0, REMOTE_APP if os.path.isdir(REMOTE_APP) else str(HERE))
from pmpstages import common as C  # noqa: E402

APP_NAME = os.environ.get('PMP_APP', 'pmp-complete')     # app_v2: the completion pipeline (app/ = pmp-partial)
VOLUME = 'pmp-out'
WITH_PLUGINS = os.environ.get('PMP_WITH_PLUGINS') == '1'   # build the src_db1 / src_sds2 images (slow) for this run
STAGE_MAX_CONTAINERS = int(os.environ.get('PMP_STAGE_MAX_CONTAINERS', '5'))   # per stage function (safety cap)
# size classes whose stage containers run on non-preemptible capacity (Modal's nonpreemptible=True, billed at 3x list price).
# Default none: a preempted stage is restarted by Modal with the same input and starts over (counted per call in
# /<id>/logs/starts.jsonl and the index row's container_restarts). For hour-long L / XL runs at scale consider
# PMP_NONPREEMPTIBLE=L,XL (a decision for the scale plan, not made here).
NONPREEMPTIBLE = {c.strip() for c in os.environ.get('PMP_NONPREEMPTIBLE', '').split(',') if c.strip()}
SYS_LIBS = ['libgl1', 'libxrender1', 'libxext6', 'libsm6', 'libfontconfig1', 'libxkbcommon0', 'libxi6']
# the ORIGINAL 5 partial samples: the owner does not want them (re)run on Modal - refused by every entrypoint
FORBIDDEN_ID_PREFIXES = ('52709163bc62d640', '61fd1bf84a60a7db', 'e0a2b664bcdec482', '7f892a3ad9b2349b', 'dcc9a4376d362e45')
FORBIDDEN_FILE = HERE / 'forbidden_ids.json'               # their full ids (from the bench summaries of s1..s5)
NEW5 = ROOT / 'new5.json'

app = modal.App(APP_NAME)
vol = modal.Volume.from_name(VOLUME, create_if_missing=True)

# ------------------------------------------------------------------------------------------------------------ images
SKIP_DIRS = {'__pycache__', '.venv', 'venv', 'tests', 'test_out', 'out', 'work', 'runs', '.git', 'cache', 'presigned',
             'testB_results', 'scratch'}
SKIP_EXT = {'.step', '.stp', '.ifc', '.db1', '.zip', '.gz', '.tgz', '.tar', '.7z', '.pyc', '.log', '.png'}


def _ignore(base, max_mb=64, skip_ext=SKIP_EXT, skip_dirs=()):
    """add_local_dir predicate (path relative to base): code + small data only, never test outputs / models / caches"""
    skip = SKIP_DIRS | set(skip_dirs)

    def ign(p):
        p = pathlib.Path(p)
        if set(p.parts) & skip or any(x.startswith('.') for x in p.parts):
            return True
        full = base / p
        if full.is_dir():
            return False
        if p.suffix.lower() in skip_ext:
            return True
        try:
            return full.stat().st_size > max_mb * 2**20
        except OSError:
            return True
    return ign


def _with_app(img):
    """the app's own code (+ the publish contract) on top of a stage image"""
    img = img.add_local_dir(HERE, REMOTE_APP, ignore=_ignore(HERE))
    if (ROOT / 'publish' / 'bundle_lib.py').exists():
        img = img.add_local_file(ROOT / 'publish' / 'bundle_lib.py', '/pmp/publish/bundle_lib.py')
    if (ROOT / 'publish_v2' / 'bundle_lib.py').exists():
        img = img.add_local_file(ROOT / 'publish_v2' / 'bundle_lib.py', '/pmp/publish_v2/bundle_lib.py')
    if (ROOT / 'complete' / 'integrate').is_dir():
        img = img.add_local_dir(ROOT / 'complete' / 'integrate', '/pmp/complete/integrate',
                                ignore=_ignore(ROOT / 'complete' / 'integrate', skip_dirs={'out', 'work'}))
    return img


def _pipe_image():
    img = (modal.Image.debian_slim(python_version='3.11')
           .apt_install(*SYS_LIBS)
           .pip_install_from_requirements(str(ROOT / 'code' / 'requirements.txt'))
           .env({'PYTHONUNBUFFERED': '1', 'OMP_NUM_THREADS': '1'}))
    for v in sorted(set(C.CODE_BY_SOURCE.values())):
        img = img.add_local_dir(ROOT / 'code' / v, f'{C.CODE_ROOT}/{v}', ignore=_ignore(ROOT / 'code' / v))
    img = img.add_local_file(ROOT / 'code' / 'requirements.txt', f'{C.CODE_ROOT}/requirements.txt')
    if (ROOT / 'issues').is_dir():
        img = img.add_local_dir(ROOT / 'issues', '/pmp/issues', ignore=_ignore(ROOT / 'issues'))
    return _with_app(img)


def _plugin_image(name):
    """the plug-in's own image (<component>/modal_image.py: build(modal, root) -> Image) + the component + the app.
    Without PMP_WITH_PLUGINS=1 (or without modal_image.py) a stub image: the stage then records plugin_image_missing."""
    d = ROOT / name
    f = d / 'modal_image.py'
    if WITH_PLUGINS and f.exists():
        spec = importlib.util.spec_from_file_location(f'pmp_img_{name}', f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        img = mod.build(modal, d)
        if not getattr(mod, 'INCLUDES_COMPONENT', False):
            # the component's code (kits / converter zips are already copied into the image by modal_image.build)
            img = img.add_local_dir(d, f'/pmp/{name}', ignore=_ignore(d, max_mb=256, skip_ext={'.pyc', '.log'},
                                                                      skip_dirs={'kits', 'converters', 'results'}))
        return _with_app(img)
    return _with_app(modal.Image.debian_slim(python_version='3.11'))


pipe_image = _pipe_image()
light_image = _with_app(modal.Image.debian_slim(python_version='3.11'))
db1_image = _plugin_image('src_db1')
sds2_image = _plugin_image('src_sds2')


# --------------------------------------------------------------------------------------------------- stage functions
def _deadline(cls):
    return time.time() + C.RES[cls]['timeout'] - C.STOP_MARGIN


def _started(job, stage):
    """record this container start of the call (preemption restarts are counted: common.record_start)"""
    n = C.record_start(job['id'], stage, job.get('_call') or f'direct/{stage}/{time.time_ns()}')
    vol.commit()
    if n > 1:
        print(f'[{job["id"][:16]} {stage}] container start {n} of this call (restarted after preemption)', flush=True)
    return n


def _stamp(rec, n):
    if isinstance(rec, dict):
        rec['container_starts'] = n
    return rec


def _src(name, job, cls, run_name):
    from pmpstages import plugins, source
    vol.reload()
    job = C.normalise_job(job)
    n = _started(job, name)
    if not plugins.available(name):
        return _stamp(source.plugin_missing(name, job, cls, f'/pmp/{name} is not in this image (deploy with PMP_WITH_PLUGINS=1 '
                                                            f'and {name}/modal_image.py + stage.py)'), n)
    try:
        return _stamp(source.run_plugin(name, job, cls, _deadline(cls)), n)
    finally:
        vol.commit()


def src_db1_impl(job, cls, run_name):
    return _src('src_db1', job, cls, run_name)


def src_sds2_impl(job, cls, run_name):
    return _src('src_sds2', job, cls, run_name)


def pipeline_impl(job, cls, ifc_spec, run_name):
    from pmpstages import pipeline
    vol.reload()
    job = C.normalise_job(job)
    n = _started(job, 'pipeline')
    try:
        return _stamp(pipeline.run(job, ifc_spec, cls, _deadline(cls)), n)
    finally:
        vol.commit()


def issues_impl(job, cls, run_name):
    from pmpstages import issues
    vol.reload()
    job = C.normalise_job(job)
    n = _started(job, 'issues')
    try:
        return _stamp(issues.run(job, cls, _deadline(cls), run_name), n)
    finally:
        vol.commit()


def _res(cls):
    r = C.RES[cls]
    # PMP_FAST_CPU / PMP_FAST_MEM_GIB (owner's "fast" run): raise the container's cpu / memory request only; J (worker
    # count given to the tools) and timeouts stay as the fleet's, so outputs are unchanged.
    cpu = max(r['cpu'], float(os.environ.get('PMP_FAST_CPU', '0') or 0))
    mem = max(r['mem_gib'], int(os.environ.get('PMP_FAST_MEM_GIB', '0') or 0))
    kw = dict(cpu=cpu, memory=mem * 1024, timeout=r['timeout'], volumes={C.VOL: vol},
              max_containers=STAGE_MAX_CONTAINERS)
    if r['disk_gib']:
        kw['ephemeral_disk'] = r['disk_gib'] * 1024
    if cls in NONPREEMPTIBLE:
        kw['nonpreemptible'] = True
    return kw


PIPE, ISSUES = {}, {}
SRC = {'regenerated_from_db1': {}, 'emitted_from_sds2': {}}
for _cls in C.CLASSES:
    PIPE[_cls] = app.function(name=f'pipeline_{_cls}', image=pipe_image, **_res(_cls))(pipeline_impl)
    ISSUES[_cls] = app.function(name=f'issues_{_cls}', image=pipe_image, **_res(_cls))(issues_impl)
    SRC['regenerated_from_db1'][_cls] = app.function(name=f'src_db1_{_cls}', image=db1_image, single_use_containers=True,
                                                                **_res(_cls))(src_db1_impl)
    SRC['emitted_from_sds2'][_cls] = app.function(name=f'src_sds2_{_cls}', image=sds2_image, **_res(_cls))(src_sds2_impl)


@app.function(image=light_image, cpu=1.0, memory=2048, timeout=3600, volumes={C.VOL: vol}, max_containers=10)
def upload_bundle(model_id, run_name, put_url, headers=None):
    """PUT the bundle of (model, run) from the volume to its pre-signed URL (re-runnable with fresh URLs)"""
    from pmpstages import package as K
    vol.reload()
    bd = f'{C.VOL}/{model_id}/bundle/{run_name}'
    p, facts = f'{bd}/{model_id}.tar.gz', C.read_json(f'{bd}/bundle_facts.json')
    if not os.path.exists(p) or not facts:
        return {'ok': False, 'error': f'no bundle on the volume for {model_id} run {run_name}'}
    if C.file_sha256(p) != facts['sha256']:
        return {'ok': False, 'error': 'the bundle on the volume differs from its bundle_facts.json'}
    r = K.upload(p, put_url, facts['md5_hex'])
    r['bundle_sha256'] = facts['sha256']
    C.write_json(f'{bd}/upload.json', dict(r, at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())))
    vol.commit()
    return r


@app.function(image=light_image, cpu=0.25, memory=1024, timeout=24 * 3600, volumes={C.VOL: vol}, max_containers=10)
def run_model(job, run_name, opts):
    """the per-model orchestrator (pmpstages/orchestrate.py) with the stage functions above"""
    from pmpstages import orchestrate

    def write_row(row):
        mid = row.get('model_id') or 'unknown'
        C.write_json(f'{C.VOL}/index/{run_name}/{mid}.json', row)
        vol.commit()

    F = {'source': {k: {c: f.remote for c, f in v.items()} for k, v in SRC.items()},
         'pipeline': {c: f.remote for c, f in PIPE.items()},
         'issues': {c: f.remote for c, f in ISSUES.items()},
         'upload': upload_bundle.remote}
    return orchestrate.orchestrate(job, run_name, opts, F, write_row,
                                   log=lambda m: print(time.strftime('%H:%M:%S ') + m, flush=True))


@app.function(image=light_image, cpu=0.25, memory=1024, timeout=1800, volumes={C.VOL: vol})
def collect_index(run_name):
    """/vol/index/<run>/<id>.json rows -> /vol/index/<run>.jsonl (sorted by model id); returns the rows"""
    vol.reload()
    d = f'{C.VOL}/index/{run_name}'
    rows = []
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.endswith('.json'):
                r = C.read_json(os.path.join(d, f))
                if r is not None:
                    rows.append(r)
    rows.sort(key=lambda r: str(r.get('model_id')))
    tmp = f'{C.VOL}/index/{run_name}.jsonl.tmp'
    with open(tmp, 'w') as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True, default=str) + '\n')
    os.replace(tmp, f'{C.VOL}/index/{run_name}.jsonl')
    vol.commit()
    return rows


@app.function(image=pipe_image, cpu=2.0, memory=4096, timeout=1800, volumes={C.VOL: vol})
def image_facts(make_closure: bool = False):
    """what the pipeline image holds: python, key packages, the code variants vs their MD5SUMS, plug-ins, templates.
    make_closure: also resolve build123d==0.13.0 in a clean venv constrained to the pipeline freeze (the shipped
    scripts/requirements.txt) and test the shipped template in another clean venv"""
    import importlib.metadata as md, platform, subprocess, tempfile
    out = {'python': platform.python_version(), 'packages': {}, 'code': {}, 'plugins': {}, 'templates': {}}
    for p in ('build123d', 'cadquery-ocp-novtk', 'ifcopenshell', 'numpy', 'scipy', 'shapely', 'psutil', 'requests'):
        try:
            out['packages'][p] = md.version(p)
        except Exception as e:
            out['packages'][p] = repr(e)
    for v in sorted(set(C.CODE_BY_SOURCE.values())):
        out['code'][v] = C.check_md5sums(f'{C.CODE_ROOT}/{v}')
    from pmpstages import plugins
    for n in ('issues', 'src_db1', 'src_sds2'):
        out['plugins'][n] = plugins.entry(n)
    out['bundle_lib'] = os.path.exists('/pmp/publish/bundle_lib.py')
    out['issues_files'] = sorted(os.listdir('/pmp/issues')) if os.path.isdir('/pmp/issues') else None
    for f in ('scripts_README.md', 'requirements.txt'):
        p = os.path.join(C.TEMPLATES, f)
        out['templates'][f] = C.file_sha256(p) if os.path.exists(p) else None
    r = subprocess.run([sys.executable, '-c', 'import build123d, OCP, ifcopenshell; print("imports ok")'], capture_output=True, text=True)
    out['imports'] = (r.stdout + r.stderr).strip()[-500:]
    # a clean environment for venvs: Modal puts its own client packages on PYTHONPATH, which a venv would inherit
    cenv = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': '/tmp', 'PIP_DISABLE_PIP_VERSION_CHECK': '1'}
    if make_closure:
        t = tempfile.mkdtemp()
        cmds = [[sys.executable, '-m', 'venv', f'{t}/v'],
                [f'{t}/v/bin/pip', 'install', '-q', 'build123d==0.13.0', '-c', f'{C.CODE_ROOT}/requirements.txt'],
                [f'{t}/v/bin/pip', 'freeze', '--all']]
        logs = []
        for c in cmds:
            r = subprocess.run(c, capture_output=True, text=True, env=cenv)
            logs.append(f'$ {" ".join(c[1:3])} rc {r.returncode}\n{r.stderr[-1500:]}')
        out['closure_freeze'] = r.stdout
        out['closure_log'] = logs
        tp = os.path.join(C.TEMPLATES, 'requirements.txt')
        if os.path.exists(tp):
            t2 = tempfile.mkdtemp()
            r1 = subprocess.run([sys.executable, '-m', 'venv', f'{t2}/v'], capture_output=True, text=True, env=cenv)
            r2 = subprocess.run([f'{t2}/v/bin/pip', 'install', '-q', '-r', tp], capture_output=True, text=True, env=cenv)
            r3 = subprocess.run([f'{t2}/v/bin/python', '-c', 'import build123d, OCP, numpy; print(build123d.__version__)'],
                                capture_output=True, text=True, env=cenv)
            r4 = subprocess.run([f'{t2}/v/bin/pip', 'freeze', '--all'], capture_output=True, text=True, env=cenv)
            out['template_venv'] = {'install_rc': r2.returncode, 'install_err': r2.stderr[-1500:], 'import': (r3.stdout + r3.stderr)[-500:],
                                    'freeze': r4.stdout}
    return out


@app.function(image=pipe_image, cpu=2.0, memory=8192, timeout=3600, volumes={C.VOL: vol})
def clean_venv_check(model_id: str):
    """the published-scripts claim 'runs from the package alone': install scripts/requirements.txt of the model's
    assembled tree (/vol/<id>/scripts_tree) into a CLEAN venv and run build_model.py --list and
    build_issues_model.py --list / --help there (no pipeline code, no image packages)"""
    import shutil, subprocess, tempfile
    vol.reload()
    S = f'{C.VOL}/{model_id}/scripts_tree'
    if not os.path.isdir(S):
        return {'ok': False, 'error': 'no scripts_tree on the volume'}
    t = tempfile.mkdtemp()
    shutil.copytree(S, f'{t}/scripts')
    res = {}
    cenv = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': '/tmp', 'PIP_DISABLE_PIP_VERSION_CHECK': '1'}   # no PYTHONPATH
    for name, c in (('venv', [sys.executable, '-m', 'venv', f'{t}/v']),
                    ('pip', [f'{t}/v/bin/pip', 'install', '-q', '-r', f'{t}/scripts/requirements.txt'])):
        r = subprocess.run(c, capture_output=True, text=True, env=cenv)
        res[name] = {'rc': r.returncode, 'tail': (r.stdout + r.stderr)[-1500:]}
    mf = [d for d in os.listdir(f'{t}/scripts') if os.path.isdir(f'{t}/scripts/{d}')][0]
    for name, args in (('build_model_list', ['build_model.py', '--list']), ('issues_help', ['build_issues_model.py', '--help']),
                       ('issues_list', ['build_issues_model.py', '--list'])):
        r = subprocess.run([f'{t}/v/bin/python'] + args, cwd=f'{t}/scripts/{mf}', capture_output=True, text=True,
                           env=dict(cenv, PYTHONDONTWRITEBYTECODE='1'))
        res[name] = {'rc': r.returncode, 'tail': (r.stdout + r.stderr)[-1500:]}
    res['ok'] = all(v['rc'] == 0 for v in res.values() if isinstance(v, dict))
    return res


# ------------------------------------------------------------------------------------------------------- driver side
def _load_rows(path):
    p = pathlib.Path(path)
    raw = gzip.open(p, 'rt').read() if p.suffix == '.gz' else p.read_text()
    raw = raw.strip()
    if raw.startswith('['):
        return json.loads(raw)
    return [json.loads(x) for x in raw.splitlines() if x.strip()]


def _forbidden():
    ids = set()
    try:
        ids |= set(json.loads(FORBIDDEN_FILE.read_text()))
    except Exception:
        pass
    return ids


def _select(rows, only='', limit=0, scale=False):
    """the jobs to run: never the original 5 samples; only new5.json models unless --scale (owner approval needed)"""
    forb = _forbidden()
    allow = None if scale else {r['model_id'] for r in json.loads(NEW5.read_text())}
    want = {x.strip() for x in only.split(',') if x.strip()}
    out = []
    for r in rows:
        mid = str(r.get('id') or r.get('model_id'))
        if mid in forb or mid.startswith(FORBIDDEN_ID_PREFIXES):
            raise SystemExit(f'refused: {mid[:16]} is one of the ORIGINAL 5 samples (never run on Modal)')
        if allow is not None and mid not in allow:
            raise SystemExit(f'refused: {mid[:16]} is not in new5.json (scale runs need --scale, after the owner approves)')
        if want and mid not in want and r.get('tag') not in want and mid[:16] not in want:
            continue
        out.append(r)
    return out[:limit] if limit else out


def _attach_urls(rows, put_urls='', get_urls='', run=''):
    """PUT URLs from publish/presign_put.py's <run>.json ({run, expires_utc, urls: {model_id: {key, url}}}); GET URLs
    from a {model_id: {alias: url}} file when the rows do not carry 'urls' already"""
    if get_urls:
        g = json.loads(pathlib.Path(get_urls).read_text())
        g = g.get('urls', g) if isinstance(g, dict) else g
        for r in rows:
            mid = str(r.get('id') or r.get('model_id'))
            if mid in g and not r.get('urls'):
                r['urls'] = g[mid]
    if put_urls:
        d = json.loads(pathlib.Path(put_urls).read_text())
        if d.get('run') and run and d['run'] != run:
            raise SystemExit(f'--put-urls were signed for run {d["run"]!r}, not {run!r}')
        for r in rows:
            mid = str(r.get('id') or r.get('model_id'))
            u = (d.get('urls') or {}).get(mid)
            if u:
                r['put_url'] = u['url'] if isinstance(u, dict) else u
    return rows


def _short(row):
    st = row.get('stages') or {}
    p, i = st.get('pipeline') or {}, st.get('issues') or {}
    return (f"{str(row.get('model_id'))[:12]} {row.get('tag') or '':14s} {row.get('status'):15s} cls {row.get('cls_final') or row.get('cls')} "
            f"perfect={p.get('perfect')} parts={p.get('parts')} counts={i.get('counts')} "
            f"bundle={(row.get('bundle') or {}).get('bytes')} upload={(row.get('upload') or {}).get('ok')} "
            f"{row.get('seconds')}s err={str(row.get('error'))[:160] if row.get('error') else ''}")


@app.local_entrypoint()
def main(jobs: str, run: str = '', limit: int = 0, concurrency: int = 4, only: str = '', put_urls: str = '',
         get_urls: str = '', upload: bool = True, max_containers: int = 10, scale: bool = False, escalate: bool = True,
         dry_run: bool = False):
    """driver: run a job list end to end (source -> pipeline -> issues/package/bundle -> upload), then merge the index"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    run = run or time.strftime('t%Y%m%d-%H%M%S')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', run):
        raise SystemExit(f'bad run name {run!r}')
    rows = _attach_urls(_select(_load_rows(jobs), only, limit, scale), put_urls, get_urls, run)
    conc = max(1, min(concurrency, max_containers // 2, len(rows) or 1))   # orchestrator + one stage container per model
    opts = {'upload': upload, 'escalate': escalate}
    print(f'run {run}: {len(rows)} jobs, {conc} at a time (<= {2 * conc} containers), upload={upload}, '
          f'plugins={"built" if WITH_PLUGINS else "stub (PMP_WITH_PLUGINS=1 to build src_db1/src_sds2)"}')
    for r in rows:
        j = C.normalise_job(r)
        ok, why = C.job_runnable(j)
        print(f'  {j["id"][:12]} {r.get("tag") or "":14s} {j["source_kind"]:21s} {j["cls"]:3s} {j["bytes"]:>11,} B '
              f'scripts/{j["model_folder"]}/ put_url={"yes" if j.get("put_url") else "no"} runnable={ok}{"" if ok else " (" + why + ")"}')
    if dry_run:
        return
    t0 = time.time()
    done = []
    with ThreadPoolExecutor(conc) as ex:
        futs = {ex.submit(run_model.remote, r, run, opts): r for r in rows}
        for f in as_completed(futs):
            r = futs[f]
            try:
                row = f.result()
            except Exception as e:
                row = {'model_id': r.get('model_id') or r.get('id'), 'tag': r.get('tag'), 'status': 'error',
                       'error': f'orchestrator call failed: {type(e).__name__}: {e}'}
            done.append(row)
            print(time.strftime('%H:%M:%S ') + _short(row), flush=True)
    idx = collect_index.remote(run)
    out = HERE / 'runs'
    out.mkdir(exist_ok=True)
    with open(out / f'{run}.jsonl', 'w') as f:
        for r in idx:
            f.write(json.dumps(r, sort_keys=True, default=str) + '\n')
    st = {}
    for r in idx:
        st[r.get('status')] = st.get(r.get('status'), 0) + 1
    print(f'run {run}: {st} in {time.time() - t0:.0f}s; index /vol/index/{run}.jsonl (volume {VOLUME}), local copy {out / (run + ".jsonl")}')


@app.local_entrypoint()
def unit_pipeline(jobs: str, tag: str = 'n4_ifc_c2s', get_urls: str = '', run: str = 'unit-pipeline'):
    """unit test of the pipeline stage alone on ONE new sample (package-IFC model): the stage runs on Modal, then its
    summary is checked here against job.py's pmx_summary (same keys, same order, verdict reproduced from the files)"""
    import tempfile
    rows = _attach_urls(_select(_load_rows(jobs), only=tag), '', get_urls, run)
    if len(rows) != 1:
        raise SystemExit(f'--tag {tag} selects {len(rows)} jobs')
    job = C.normalise_job(rows[0])
    if job['source_kind'] != 'package_ifc':
        raise SystemExit('unit_pipeline runs package-IFC models only (DB1 / SDS/2 need their source stage first)')
    ok, why = C.job_runnable(job)
    if not ok:
        raise SystemExit(f'not runnable: {why}')
    cls = job['cls']
    print(f'pipeline_{cls} on {job["id"][:16]} ({tag}, {job["bytes"]:,} B, code {job["code_version"]})')
    t0 = time.time()
    res = PIPE[cls].remote(rows[0], cls, {'mode': 'package', 'url_key': 'ifc'}, run)
    print(json.dumps({k: res.get(k) for k in ('ok', 'error', 'perfect', 'reasons', 'parts', 'status', 'steps', 'step_seconds',
                                               'seconds', 'cpu_seconds', 'peak_gib', 'peak_how', 'memory_killed_steps', 'source')},
                     indent=1, default=str))
    # ---- checks on what the stage left on the volume
    base = f'/{job["id"]}/pipeline'
    summ = json.loads(b''.join(vol.read_file(f'{base}/summary.json')))
    from pmpstages.pipeline import STEPS, make_verdict
    td = tempfile.mkdtemp(prefix='pmp_unit_')
    names = [e.path.split('/')[-1] for e in vol.listdir(f'{base}/out')]
    for n in ('verification_summary.json', 'levels_summary.json', 'e2e_summary.json', 'reference_defects_summary.json',
              'recover_summary.json'):
        if n in names:
            with open(os.path.join(td, n), 'wb') as f:
                for b in vol.read_file(f'{base}/out/{n}'):
                    f.write(b)
    ver = make_verdict(td)(summ['steps'])
    jobpy_env = ['id', 'gen', 'stem', 'pid', 'step', 'ifc', 'bytes', 'cls', 'tool', 'J', 'code', 'host', 'iid', 'region', 'itype',
                 'seconds', 'finished', 'peak_rss_gb']
    checks = {
        'stage_ok': bool(res.get('ok')),
        'all_steps_ran': list(summ['steps']) == ['download'] + list(STEPS),
        'summary_keys_as_job_py': list(summ) == list(ver) + jobpy_env,
        'verdict_reproduced_from_files': all(json.dumps(summ.get(k), sort_keys=True) == json.dumps(v, sort_keys=True) for k, v in ver.items()),
        'out_has_schedules': all(n in names for n in ('parts.csv', 'profiles.csv', 'solids.csv', 'verification.csv')),
        'source_provenance': bool(res.get('source') and res['source'].get('sha256_checked_against')),
        'e2e_inputs_recorded': bool(json.loads(b''.join(vol.read_file(f'{base}/e2e_inputs.json'))).get('files')),
        'summary_has_no_urls': 'X-Amz-' not in json.dumps(summ),
    }
    print('checks:', json.dumps(checks, indent=1))
    print(f'unit_pipeline {"PASS" if all(checks.values()) else "FAIL"} in {time.time() - t0:.0f}s; outputs on volume {VOLUME}:{base}/')


@app.local_entrypoint()
def check_image(closure: bool = False):
    """what the images hold (no model is run)"""
    print(json.dumps(image_facts.remote(closure), indent=1, default=str))


@app.local_entrypoint()
def upload(run: str, put_urls: str, only: str = ''):
    """re-upload the bundles of a run that are on the volume, with fresh PUT URLs (publish/presign_put.py output)"""
    d = json.loads(pathlib.Path(put_urls).read_text())
    if d.get('run') != run:
        raise SystemExit(f'PUT URLs are for run {d.get("run")!r}, not {run!r}')
    want = {x for x in only.split(',') if x}
    for mid, u in sorted((d.get('urls') or {}).items()):
        if want and mid not in want:
            continue
        r = upload_bundle.remote(mid, run, u['url'] if isinstance(u, dict) else u)
        print(mid[:16], json.dumps({k: r.get(k) for k in ('ok', 'http', 'etag', 'bytes', 'error')}))


@app.local_entrypoint()
def collect(run: str):
    """merge /vol/index/<run>/*.json into /vol/index/<run>.jsonl and print the rows"""
    for r in collect_index.remote(run):
        print(_short(r))


# ---- testB: reproduce a PUBLISHED scripts/ tree (downloaded read-only from S3 on the Mac) in a fresh container
@app.function(image=pipe_image, cpu=16.0, memory=64 * 1024, timeout=4 * 3600, max_containers=5)
def repro_published(tree_tgz: bytes, step_url: str, step_rel: str, step_sha256: str, model_folder: str, jobs: int = 16):
    import io, subprocess, tarfile, tempfile
    from pmpstages import common as CC
    t0 = time.time()
    R = tempfile.mkdtemp()
    tarfile.open(fileobj=io.BytesIO(tree_tgz)).extractall(R)
    M = os.path.join(R, 'scripts', model_folder)
    pub = {f: CC.step_data_sha256(os.path.join(M, 'issues', f)) for f in os.listdir(os.path.join(M, 'issues')) if f.endswith('.step')}
    os.makedirs(os.path.join(R, 'pub'))
    for f in pub:
        os.rename(os.path.join(M, 'issues', f), os.path.join(R, 'pub', f))   # the scripts must regenerate them
    CC.download(step_url, os.path.join(R, step_rel), sha256=step_sha256 or None)
    res = {'published_data_sha256': pub, 'runs': {}}

    def run(name, cmd):
        a = time.time()
        p = subprocess.run([sys.executable] + cmd, cwd=M, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        res['runs'][name] = {'cmd': ' '.join(cmd), 'rc': p.returncode, 'seconds': round(time.time() - a, 1), 'tail': p.stdout[-1200:]}
    run('build_model', ['build_model.py', '--jobs', str(jobs), '--out', os.path.join(R, 'rebuilt.step')])
    rb = os.path.join(R, 'rebuilt.step')
    res['rebuilt'] = {'bytes': os.path.getsize(rb), 'data_sha256': CC.step_data_sha256(rb)} if os.path.exists(rb) else None
    run('issues_list', ['build_issues_model.py', '--list'])
    run('build_issues_model', ['build_issues_model.py', '--jobs', str(jobs), '--verify'])
    got = {f: CC.step_data_sha256(os.path.join(M, 'issues', f)) for f in os.listdir(os.path.join(M, 'issues')) if f.endswith('.step')}
    res['regenerated_data_sha256'] = got
    res['issues_step_reproduced'] = bool(pub) and got == pub
    diffs = []
    for f in got:
        if f in pub and got[f] != pub[f]:
            a = open(os.path.join(R, 'pub', f), errors='replace').read().split('DATA;', 1)[-1].splitlines()
            b = open(os.path.join(M, 'issues', f), errors='replace').read().split('DATA;', 1)[-1].splitlines()
            dl = [(i, x[:300], y[:300]) for i, (x, y) in enumerate(zip(a, b)) if x != y]
            diffs.append({'file': f, 'lines_pub': len(a), 'lines_new': len(b), 'n_diff': len(dl), 'first': dl[:12]})
    res['diffs'] = diffs
    res['seconds'] = round(time.time() - t0, 1)
    return res


@app.local_entrypoint()
def repro(tree_dir: str, jobs_file: str, tag: str, out: str, jobs: int = 16):
    import io, tarfile
    row = next(json.loads(l) for l in open(jobs_file) if json.loads(l).get('tag') == tag)
    j = C.normalise_job(row)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tf:
        tf.add(os.path.join(tree_dir, 'scripts'), arcname='scripts')
    r = repro_published.remote(buf.getvalue(), row['urls']['step'], j['step'].lstrip('/'), j.get('step_sha256') or '', j['model_folder'], jobs)
    open(out, 'w').write(json.dumps(r, indent=1))
    print(tag, 'reproduced' if r['issues_step_reproduced'] else 'NOT REPRODUCED', {k: v['rc'] for k, v in r['runs'].items()}, r['seconds'], 's')


# ===================================================================================================== completion (app_v2)
COMPLETE_CPU = float(os.environ.get('PMP_COMPLETE_CPU', '16'))
COMPLETE_MEM_GIB = int(os.environ.get('PMP_COMPLETE_MEM_GIB', '64'))


def complete_source_impl(job, cls, track, run_name):
    from pmpstages import complete as K
    vol.reload()
    job = C.normalise_job(job)
    n = _started(job, f'complete_source_{track}')
    try:
        return _stamp(K.source_pipeline(job, track, cls, _deadline(cls)), n)
    finally:
        vol.commit()


CSRC = {}
for _cls in C.CLASSES:
    CSRC[_cls] = app.function(name=f'complete_source_{_cls}', image=pipe_image, **_res(_cls))(complete_source_impl)


@app.function(image=pipe_image, cpu=COMPLETE_CPU, memory=COMPLETE_MEM_GIB * 1024, timeout=6 * 3600, volumes={C.VOL: vol},
              max_containers=5)
def complete_stage(job, run_name, patches, opts):
    """merge + shipped scripts + verify + coloured/plain builds (twice) + CHANGES.md -> /vol/<id>/complete_integrate/<run>/"""
    from pmpstages import complete as K
    vol.reload()
    job = C.normalise_job(job)
    n = _started(job, 'complete')
    try:
        opts = dict(opts or {}, jobs=int(opts.get('jobs') or max(1, int(COMPLETE_CPU * 2) - 2)))
        return _stamp(K.run(job, job['cls'], time.time() + 6 * 3600 - 600, run_name, patches, opts), n)
    finally:
        vol.commit()


@app.function(image=pipe_image, cpu=2.0, memory=8192, timeout=3600, volumes={C.VOL: vol}, max_containers=5)
def complete_bundle(job, run_name):
    from pmpstages import complete as K
    vol.reload()
    job = C.normalise_job(job)
    try:
        return K.bundle(job, run_name)
    finally:
        vol.commit()


@app.function(image=light_image, cpu=1.0, memory=2048, timeout=3600, volumes={C.VOL: vol}, max_containers=5)
def complete_upload(model_id, run_name, put_url):
    from pmpstages import package as K
    vol.reload()
    bd = f'{C.VOL}/{model_id}/complete_integrate/{run_name}/bundle'
    p, facts = f'{bd}/{model_id}.tar.gz', C.read_json(f'{bd}/bundle_facts.json')
    if not os.path.exists(p) or not facts:
        return {'ok': False, 'error': f'no completed bundle on the volume for {model_id} run {run_name}'}
    if C.file_sha256(p) != facts['sha256']:
        return {'ok': False, 'error': 'the bundle on the volume differs from its bundle_facts.json'}
    r = K.upload(p, put_url, facts['md5_hex'])
    r['bundle_sha256'] = facts['sha256']
    C.write_json(f'{bd}/upload.json', dict(r, at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())))
    vol.commit()
    return r


def _track_patches(tag):
    """complete/<track>/out/<tag>/patch.json of every track (validated locally first)"""
    sys.path.insert(0, str(ROOT / 'complete' / 'integrate'))
    import completion_core as cc
    out = {}
    short = {'n1_db1_small': 'n1', 'n2_db1_addon': 'n2', 'n3_ifc_approx': 'n3', 'n4_ifc_c2s': 'n4', 'n5_sds2': 'n5'}.get(tag)
    for tr in cc.TRACK_ORDER:
        f = ROOT / 'complete' / tr / 'out' / tag / 'patch.json'
        if not f.exists() and short:
            f = ROOT / 'complete' / tr / 'out' / short / 'patch.json'
        if f.exists():
            p = json.loads(f.read_text())
            errs = cc.validate_patch(p, tag)
            if errs:
                print(f'  {tag}: {tr} patch INVALID ({len(errs)}): {errs[:3]} - skipped')
                continue
            out[tr] = p
    # two non-exact replace_part of one part: the later track (merge order) is the one built, drop the earlier
    last = {}
    for tr in cc.TRACK_ORDER:
        for o in (out.get(tr) or {}).get('ops', []):
            if o.get('op') == 'replace_part' and o.get('colour') != 'GREEN':
                last[o['part_id']] = tr
    for tr in cc.TRACK_ORDER:
        if tr in out:
            out[tr]['ops'] = [o for o in out[tr]['ops'] if not (o.get('op') == 'replace_part' and o.get('colour') != 'GREEN'
                                                                 and last.get(o['part_id'], tr) != tr)]
    # an exact (GREEN) restoration of an earlier track wins over a later estimate/standard of the same part
    taken, sup = set(), set()
    for tr in cc.TRACK_ORDER:
        p = out.get(tr)
        if not p:
            continue
        keep = []
        for o in p['ops']:
            if o.get('part_id') in taken or (set(o.get('supersedes') or []) & sup):
                print(f"  {tag}: {tr} op {o.get('id')} dropped (part already restored from source by an earlier track)")
                continue
            keep.append(o)
        p['ops'] = keep
        for o in keep:
            if o.get('colour') == 'GREEN':
                if o.get('part_id'):
                    taken.add(o['part_id'])
                sup.update(o.get('supersedes') or [])
    return out


@app.local_entrypoint()
def complete_main(jobs: str = str(ROOT / 'jobs' / 'urls' / 'new5.signed.jsonl'), run: str = '', only: str = '',
                  source_tracks: str = '', no_formb: bool = False, bundle: bool = True, put_urls: str = '',
                  dry_run: bool = False, test_patch: str = '', test_track: str = 'standards'):
    """the completion of the new5 models: [Form B source pipelines for --source-tracks] -> complete_stage -> bundle
    [-> upload with --put-urls]. Results: /vol/<id>/complete_integrate/<run>/ + app_v2/runs/<run>.complete.jsonl"""
    from concurrent.futures import ThreadPoolExecutor
    run = run or time.strftime('c%Y%m%d-%H%M%S')
    rows = _select(_load_rows(jobs), only, 0, False)
    puts = json.loads(pathlib.Path(put_urls).read_text()).get('urls', {}) if put_urls else {}
    st = [t for t in source_tracks.split(',') if t]
    plan = []
    for r in rows:
        j = C.normalise_job(r)
        pt = _track_patches(r.get('tag'))
        if test_patch:                                  # a synthetic patch instead of the tracks' (tests only)
            pt = {test_track: json.loads(pathlib.Path(test_patch).read_text())}
        plan.append((r, j, pt))
        print(f"  {r.get('tag'):14s} {j['id'][:12]} cls {j['cls']} patches {sorted(pt)} source_tracks {st}")
    if dry_run:
        return

    def one(item):
        r, j, pt = item
        t0 = time.time()
        rec = {'tag': r.get('tag'), 'model_id': j['id'], 'run': run}
        for tr in st:
            try:
                rec[f'source_{tr}'] = {k: v for k, v in CSRC[j['cls']].remote(r, j['cls'], tr, run).items()
                                       if k in ('ok', 'error', 'perfect', 'reasons', 'parts', 'status', 'steps', 'seconds')}
            except Exception as e:
                rec[f'source_{tr}'] = {'ok': False, 'error': repr(e)[:500]}
            print(f"[{r.get('tag')}] source {tr}: {json.dumps(rec[f'source_{tr}'], default=str)[:400]}", flush=True)
        try:
            rec['complete'] = complete_stage.remote(r, run, pt, {'form_b': not no_formb})
        except Exception as e:
            rec['complete'] = {'ok': False, 'error': repr(e)[:800]}
        c = rec['complete']
        print(f"[{r.get('tag')}] complete ok={c.get('ok')} counts={c.get('counts')} det={c.get('determinism', {}).get('coloured_identical')}"
              f"/{c.get('determinism', {}).get('plain_identical')} err={c.get('error')}", flush=True)
        if bundle and c.get('tree'):
            try:
                rec['bundle'] = complete_bundle.remote(r, run)
            except Exception as e:
                rec['bundle'] = {'ok': False, 'error': repr(e)[:500]}
            if puts.get(j['id']) and rec['bundle'].get('ok'):
                rec['upload'] = complete_upload.remote(j['id'], run, puts[j['id']])
        rec['seconds'] = round(time.time() - t0, 1)
        return rec

    with ThreadPoolExecutor(max(1, len(plan))) as ex:
        recs = list(ex.map(one, plan))
    outp = HERE / 'runs' / f'{run}.complete.jsonl'
    outp.parent.mkdir(exist_ok=True)
    with open(outp, 'w') as f:
        for rec in recs:
            f.write(json.dumps(rec, default=str) + '\n')
    print(f'run {run}: {len(recs)} models -> {outp}')


@app.local_entrypoint()
def n3_baseline(jobs: str = str(ROOT / 'jobs' / 'urls' / 'new5.signed.jsonl'), run: str = 'c3base'):
    """n3: the baseline pipeline + issues on the IFC whose dangling #0 operator origin is repaired (volume copy)"""
    r = [x for x in _load_rows(jobs) if x.get('tag') == 'n3_ifc_approx'][0]
    j = C.normalise_job(r)
    path = f"{C.VOL}/{j['id']}/complete_sds2_ifc/sanitized_source.ifc"
    p = PIPE[j['cls']].remote(r, j['cls'], {'mode': 'volume', 'path': path}, run)
    print('pipeline', json.dumps({k: p.get(k) for k in ('ok', 'steps', 'parts', 'error', 'reasons')}, default=str)[:1500])
    i = ISSUES[j['cls']].remote(r, j['cls'], run)
    print('issues', json.dumps({k: i.get(k) for k in ('ok', 'error', 'counts')}, default=str)[:1500])
