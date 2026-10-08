"""modal_src_db1.py - Modal stage "src_db1": DB1 -> faithful source IFC (+ reproduction proof, + skipped records).

Image  : modal_image.build(): amazonlinux:2023 (the conversion fleet's OS) + Modal's python 3.11 (runtime, runs stage.py)
         + micromamba conda env /opt/conv/env = the exact 310-package bench env
         (env/conda_env.lock.txt: python 3.11.17, pythonocc-core 8.0.1 / OCC 8.0.1, ifcopenshell 0.9.0 = STEP read-back
         verifier + tools) + venv /opt/conv/ifc84 = the exact decoder / STEP-stage venv (env/ifc84.requirements.txt:
         ifcopenshell 0.8.4.post1, numpy 2.4.6) + decoder kits /opt/kits/kit_v (z3-db1-2026-10-01v) and kit_u
         (z3-db1-2026-10-01u), md5-gated against their S3 version-history manifests (env/check_kits.py) + env gate
         (env/check_env.py: installed envs must equal the locks exactly). No credentials anywhere: inputs are pre-signed
         GET URLs in the job, outputs go to the Modal Volume.
Host   : needs an AVX-512 CPU (stage.py docstring). On an AVX2-only host the stage returns host_unsuitable before
         downloading anything; this function then logs the draw to <model>/logs/src_db1_host_draws.jsonl on the volume,
         stops taking inputs (modal.experimental.stop_fetching_inputs) and raises HostUnsuitableError, and Modal retries
         the input on a new container (single_use_containers=True: every call / retry gets a fresh container - without
         it, retries were seen landing on the same AVX2 container; retries=HOST_RETRIES, Modal's maximum 10; main()
         re-spawns a call that still ends
         host-unsuitable, HOST_RESPAWNS times). ~1/3 of unpinned containers have AVX-512 (tests/results/cpu_census.json).
Output : Volume "pmp-out" /<out_root>/<model_id>/source/{model.ifc, provenance.json, skipped_records.json}
                                               /logs/src_db1/{src_db1.log, src_db1_run.json, db1_decoder_stats.json, ...}
         (out_root '' = the canonical /<model_id>/...; unit tests use '_unit/src_db1').

Use from the app:   from src_db1.modal_src_db1 import build_image, RES, stage_call  (or import this file's image + the
                    stage.py plug-in, see README.md)
Unit test (Mac):    .venv/bin/modal run src_db1/modal_src_db1.py::main --jobs src_db1/tests/jobs_n1n2.urls.json --only n1
Only the 5 NEW sample models (new5.json) may be run (hard allowlist in main())."""
import json, os, shutil, sys, time

import modal

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APP_NAME = 'pmp-src-db1'
VOLUME = 'pmp-out'
VOL = '/vol'
CODE_FILES = ['stage.py', 'regen_core.py', 'stepcmp.py', 'db1_facts.py', 'cpu_facts.py']
# Modal allows at most 10 retries per call: P(no AVX-512 host in 11 draws) ~ (2/3)^11 = 1.2 %; the caller re-spawns a call
# that still ends in HostUnsuitableError (main(): up to HOST_RESPAWNS more calls -> 33 draws, ~0.002 %). A draw costs a
# container start + ~2 s.
HOST_RETRIES = 10
HOST_RESPAWNS = int(os.environ.get('PMP_DB1_RESPAWNS', '2'))
# Optional region pin (deploy-time env): Modal refuses cloud pinning here but accepts region=. 'ap-southeast' gave 6/6
# AVX-512 hosts (AWS Skylake-SP x5, Azure Zen 4; tests/results/cpu_census.json) and is the conversion fleet's own region;
# unpinned, sequential retries kept landing on AVX2 hosts (n2: 16 draws). Modal bills region-pinned functions at a premium,
# so this is the owner's call: unset = unpinned + host shopping.
REGION = os.environ.get('PMP_DB1_REGION') or None
# per size class of the delivered STEP (decimal bytes: S < 1e7 <= M < 1e8 <= L < 5e8 <= XL < 1e9; >= 1e9 out of scope v1).
# The STEP stage runs with --threads 4 exactly as production (thread count is part of the reproduced command); the decoder
# is single threaded. Two full STEP conversions per kit attempt (regenerated + restored IFC), up to two kit attempts.
RES = {
    'S': dict(cpu=4.0, memory=16 * 1024, timeout=3 * 3600),
    'M': dict(cpu=4.0, memory=32 * 1024, timeout=10 * 3600),
    'L': dict(cpu=6.0, memory=64 * 1024, timeout=20 * 3600),
    'XL': dict(cpu=8.0, memory=128 * 1024, timeout=24 * 3600),
}
STOP_MARGIN = 600


class HostUnsuitableError(RuntimeError):
    """raised by the src_db1 function on an AVX2-only host so that Modal retries the input on another container"""


def size_class(nbytes):
    b = int(nbytes or 0)
    return 'S' if b < 10**7 else 'M' if b < 10**8 else 'L' if b < 5 * 10**8 else 'XL' if b < 10**9 else 'too_big_v1'


def build_image():
    """modal_image.build (the stage image, shared with the app's plug-in loader) + this component's code at /pmp/src_db1"""
    import importlib.util
    here_img = os.path.join(HERE, 'modal_image.py')
    path = here_img if os.path.exists(here_img) else '/pmp/src_db1/modal_image.py'      # in-container re-import
    spec = importlib.util.spec_from_file_location('pmp_src_db1_modal_image', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    img = mod.build(modal, HERE)
    for fn in CODE_FILES + ['modal_image.py']:
        img = img.add_local_file(os.path.join(HERE, fn), f'/pmp/src_db1/{fn}')
    return img


app = modal.App(APP_NAME)
vol = modal.Volume.from_name(VOLUME, create_if_missing=True)
image = build_image()


def _publish(local_out, mid, out_root):
    """local stage output -> /vol/<out_root>/<mid>/source (replaced as a whole) + /logs/src_db1 (replaced)"""
    base = os.path.join(VOL, out_root, mid) if out_root else os.path.join(VOL, mid)
    os.makedirs(base, exist_ok=True)
    for src, dst in ((os.path.join(local_out, 'source'), os.path.join(base, 'source')),
                     (os.path.join(local_out, 'logs'), os.path.join(base, 'logs', 'src_db1'))):
        tmp, old = dst + '.tmp', dst + '.old'
        for p in (tmp, old):
            shutil.rmtree(p, ignore_errors=True)
        shutil.copytree(src, tmp)
        if os.path.exists(dst):
            os.rename(dst, old)
        os.rename(tmp, dst)
        shutil.rmtree(old, ignore_errors=True)
    return base


@app.function(image=image, volumes={VOL: vol}, max_containers=10, single_use_containers=True, region=REGION,
              retries=modal.Retries(max_retries=HOST_RETRIES, backoff_coefficient=1.0, initial_delay=1.0), **RES['S'])
def src_db1(job: dict, out_root: str = '') -> dict:
    """one DB1-sourced model: regenerate + prove + restore + facts; outputs on the volume; returns the stage result"""
    sys.path.insert(0, '/pmp/src_db1')
    import stage
    t0 = time.time()
    try:
        vol.reload()          # see the host draws earlier attempts of this call committed
    except Exception:
        pass
    mid = job.get('model_id') or job.get('id')
    cls = job.get('class') or size_class((job.get('step') or {}).get('bytes') or job.get('bytes'))
    tmo = (RES.get(cls) or RES['S'])['timeout']
    work = f'/tmp/pmp_src_db1/{mid[:24]}'
    shutil.rmtree(work, ignore_errors=True)
    local_out = os.path.join(work, 'out')
    logf = os.path.join(work, 'stage.log')
    os.makedirs(work, exist_ok=True)

    def log(msg):
        line = time.strftime('%H:%M:%S ') + str(msg)
        with open(logf, 'a') as f:
            f.write(line + '\n')
        print(line, flush=True)

    rec = stage.run_standalone(job, os.path.join(work, 'w'), local_out, log=log, deadline=t0 + tmo - STOP_MARGIN)
    if rec.get('verdict') == 'host_unsuitable':
        base = os.path.join(VOL, out_root, mid) if out_root else os.path.join(VOL, mid)
        os.makedirs(os.path.join(base, 'logs'), exist_ok=True)
        with open(os.path.join(base, 'logs', 'src_db1_host_draws.jsonl'), 'a') as f:
            f.write(json.dumps({'call': job.get('_call'), 't': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                                'task': os.environ.get('MODAL_TASK_ID'),
                                'cloud': os.environ.get('MODAL_CLOUD_PROVIDER'), 'region': os.environ.get('MODAL_REGION'),
                                'cpu': {k: (rec.get('host_cpu') or {}).get(k) for k in ('vendor', 'family', 'model', 'flags')},
                                'verdict': 'host_unsuitable'}) + '\n')
        vol.commit()
        shutil.rmtree(work, ignore_errors=True)
        stage.stop_fetching_inputs()
        raise HostUnsuitableError(rec.get('reason'))
    rec['class'] = cls
    rec['container'] = {'task_id': os.environ.get('MODAL_TASK_ID'), 'region': os.environ.get('MODAL_REGION'),
                        'cloud': os.environ.get('MODAL_CLOUD_PROVIDER'), 'image_id': os.environ.get('MODAL_IMAGE_ID'),
                        'nproc': os.cpu_count()}
    try:
        rec['micromamba'] = open('/opt/conv/micromamba.version').read().strip()
    except Exception:
        pass
    shutil.copyfile(logf, os.path.join(local_out, 'logs', 'stage.log'))
    json.dump(rec, open(os.path.join(local_out, 'logs', 'src_db1_stage.json'), 'w'), indent=1, default=str)
    rec['volume_dir'] = _publish(local_out, mid, out_root)
    draws = os.path.join(rec['volume_dir'], 'logs', 'src_db1_host_draws.jsonl')
    rec['host_draws_before_this'] = (sum(1 for l in open(draws) if json.loads(l).get('call') == job.get('_call'))
                                     if os.path.exists(draws) and job.get('_call') else None)
    vol.commit()
    shutil.rmtree(work, ignore_errors=True)
    return rec


@app.function(image=image, volumes={VOL: vol}, max_containers=10, single_use_containers=True, region=REGION,
              retries=modal.Retries(max_retries=HOST_RETRIES, backoff_coefficient=1.0, initial_delay=1.0), **RES['S'])
def plugin_check(job: dict, out_root: str = '_unit/src_db1_plugin') -> dict:
    """the app's plug-in contract, exactly as app/pmpstages/source.run_plugin drives it: stage.run(job, ctx) with an
    app-normalised job (C.normalise_job, done on the Mac) and a ctx {stage, work, out, log, deadline, cls}. On an AVX2
    host stage.run returns {'ok': False, 'retryable': True, 'verdict': 'host_unsuitable'}; this check then does what the
    app's caller has to do: raise (HostUnsuitableError) so that Modal retries on a new container.
    Copies ctx['out'] to /vol/<out_root>/<id>/source and returns the contract fields."""
    sys.path.insert(0, '/pmp/src_db1')
    import stage
    mid = job['id']
    work = f'/tmp/pmp_plugin/{mid[:16]}'
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(os.path.join(work, 'work'))
    os.makedirs(os.path.join(work, 'out'))
    lines = []
    ctx = dict(stage='src_db1', work=os.path.join(work, 'work'), out=os.path.join(work, 'out'), cls=job.get('cls'),
               deadline=time.time() + RES['S']['timeout'] - STOP_MARGIN, log=lambda m: lines.append(str(m)))
    r = stage.run(job, ctx)
    out = ctx['out']
    files = sorted(os.listdir(out))
    if r.get('retryable'):
        assert not files, f'host_unsuitable left files in ctx[out]: {files}'
        raise HostUnsuitableError(r.get('error'))
    dst = os.path.join(VOL, out_root, mid, 'source')
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(out, dst)
    os.makedirs(os.path.join(VOL, out_root, mid, 'logs'), exist_ok=True)
    with open(os.path.join(VOL, out_root, mid, 'logs', 'src_db1.log'), 'w') as f:
        f.write('\n'.join(lines) + '\n')
    vol.commit()
    got = stage.sha256_file(os.path.join(out, r['ifc'])) if r.get('ok') and r.get('ifc') else None
    return {'ok': r.get('ok'), 'error': r.get('error'), 'verdict': r.get('verdict'), 'ifc': r.get('ifc'), 'sha256': r.get('sha256'),
            'sha256_recomputed': got, 'files_in_out': files, 'provenance_verdict': (r.get('provenance') or {}).get('verdict'),
            'kit': r.get('kit'), 'profile': r.get('profile'), 'host_cpu': r.get('host_cpu'), 'log_lines': len(lines),
            'regen_log_lines': sum(1 for l in lines if l.startswith('regen| '))}


@app.function(image=image, volumes={VOL: vol}, cpu=1.0, memory=2048, timeout=600)
def env_report() -> dict:
    """image self-check: env gate + kit gate output (no inputs)"""
    import subprocess
    sys.path.insert(0, '/pmp/src_db1')
    import stage
    out = {'runtime_PYTHONPATH': os.environ.get('PYTHONPATH'), 'note': 'gates run with stage.decoder_env() (PYTHONPATH removed)'}
    for name, cmd in (('env', 'PATH=/opt/conv/bin:$PATH MAMBA_ROOT_PREFIX=/opt/conv/mamba python /opt/pmp_env/check_env.py '
                              '/opt/pmp_env/conda_env.lock.txt /opt/pmp_env/ifc84.requirements.txt'),
                      ('kits', 'python /opt/pmp_env/check_kits.py /opt/kits /opt/kits/_manifests')):
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=stage.decoder_env())
        out[name] = {'rc': r.returncode, 'tail': (r.stdout + r.stderr)[-1500:]}
    return out


def load_jobs(path):
    txt = open(path).read().strip()
    if txt.startswith('['):
        return json.loads(txt)
    return [json.loads(l) for l in txt.splitlines() if l.strip()]


@app.local_entrypoint()
def plugin(tag: str = 'n1', jobs: str = 'jobs/urls/new5.signed.jsonl'):
    """plug-in contract check on ONE new DB1 sample, with the jobs component's signed row normalised by the app"""
    sys.path.insert(0, os.path.join(ROOT, 'app'))
    from pmpstages import common as C
    allowed = {r['model_id'] for r in json.load(open(os.path.join(ROOT, 'new5.json')))}
    rows = [r for r in load_jobs(os.path.join(ROOT, jobs)) if (r.get('tag') or '').startswith(tag)]
    if len(rows) != 1 or rows[0]['model_id'] not in allowed or rows[0].get('step_source') != 'db1':
        raise SystemExit('refused: exactly one new DB1 sample (new5.json) must match --tag')
    job = C.normalise_job(rows[0])
    r = None
    for k in range(HOST_RESPAWNS + 1):
        try:
            r = plugin_check.remote(dict(job, _call=f'plugin/{time.time_ns()}'))
            break
        except Exception as e:
            r = {'ok': False, 'error': f'{type(e).__name__}: {str(e)[:500]}', 'raised': True}
            print(f'  attempt {k + 1}: {r["error"][:300]}', flush=True)
            if 'host_unsuitable' not in str(e) and 'HostUnsuitable' not in str(e) and 'no AVX-512' not in str(e):
                break
    os.makedirs(os.path.join(HERE, 'tests', 'results'), exist_ok=True)
    json.dump(r, open(os.path.join(HERE, 'tests', 'results', f'plugin_{rows[0]["tag"]}.json'), 'w'), indent=1, default=str)
    print(json.dumps(r, indent=1, default=str)[:3000])


@app.local_entrypoint()
def main(jobs: str = '', only: str = '', out_root: str = '_unit/src_db1', env_only: bool = False, repeat: int = 1):
    """repeat > 1: the same model N times at once in separate containers (out_root/r<i>) - the cross-host determinism check"""
    if env_only:
        print(json.dumps(env_report.remote(), indent=1))
        return
    allowed = {r['model_id'] for r in json.load(open(os.path.join(ROOT, 'new5.json')))}
    J = load_jobs(jobs)
    sel = [j for j in J if not only or any((j.get('tag') or '').startswith(o) or (j.get('model_id') or '').startswith(o)
                                          for o in only.split(','))]
    for j in sel:
        if j.get('model_id') not in allowed:
            raise SystemExit(f'refused: {j.get("model_id")} is not one of the 5 new sample models (new5.json)')
        if j.get('step_source', 'db1') != 'db1':
            raise SystemExit(f'refused: {j.get("tag")} is not a DB1-sourced model')
    if not sel:
        raise SystemExit('no job selected')
    calls = []
    for j in sel:
        cls = j.get('class') or size_class((j.get('step') or {}).get('bytes') or j.get('bytes'))
        if cls not in RES:
            print(json.dumps({'model_id': j['model_id'], 'verdict': 'too_big_v1'}))
            continue
        fn = src_db1.with_options(**RES[cls])
        for i in range(max(1, repeat)):
            root = out_root if repeat <= 1 else f'{out_root}/r{i + 1}'
            print(f'spawn {j.get("tag")} {j["model_id"][:16]} class {cls} {RES[cls]} -> {root}', flush=True)
            calls.append((j, '' if repeat <= 1 else f'.r{i + 1}', fn.spawn(dict(j, _call=f'unit/{time.time_ns()}'), root)))
    os.makedirs(os.path.join(HERE, 'tests', 'results'), exist_ok=True)
    for j, suffix, c in calls:
        r = None
        for k in range(HOST_RESPAWNS + 1):
            try:
                r = c.get()
                break
            except Exception as e:
                r = {'model_id': j['model_id'], 'tag': j.get('tag'), 'ok': False, 'verdict': 'modal_error',
                     'reason': f'{type(e).__name__}: {e}'}
                if 'host_unsuitable' not in str(e) and 'HostUnsuitable' not in type(e).__name__ and 'no AVX-512' not in str(e):
                    break
                r['verdict'] = 'host_unsuitable'
                if k == HOST_RESPAWNS:
                    break
                print(f'  {j.get("tag")}{suffix}: {HOST_RETRIES + 1} draws without an AVX-512 host; re-spawning', flush=True)
                root = out_root if not suffix else f'{out_root}/{suffix[1:]}'
                c = src_db1.with_options(**RES[j.get('class') or 'S']).spawn(dict(j, _call=f'unit/{time.time_ns()}'), root)
        r.pop('downloads_urls', None)
        p = os.path.join(HERE, 'tests', 'results', f'{j.get("tag") or j["model_id"][:16]}{suffix}.json')
        json.dump(r, open(p, 'w'), indent=1, default=str)
        print(json.dumps({k: r.get(k) for k in ('tag', 'model_id', 'ok', 'verdict', 'reason', 'kit', 'profile', 'seconds', 'peak_gib',
                                                'host_draws_before_this')}), flush=True)
        print('  host', json.dumps({k: (r.get('host_cpu') or {}).get(k) for k in ('vendor', 'family', 'model', 'numpy', 'openblas_core')}))
        print('  ifc', json.dumps(r.get('ifc')), '\n  skipped_records', json.dumps(r.get('skipped_records'))[:1500], flush=True)
