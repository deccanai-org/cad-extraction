"""modal_complete_db1.py - Modal app 'pmp-complete-db1': DB1 restoration (GREEN) of the new DB1 samples n1 / n2.

Image = the src_db1 stage image (src_db1/modal_image.py: AL2023 + the exact decoder venv / conda env + kit_v / kit_u) + kit_g
(= kit_v + completion flags + restoration log, /opt/kits/kit_g) + src_db1/{regen_core, cpu_facts, stepcmp}.py + this track's
complete_core.py / ifc_canon.py. Needs an AVX-512 host (the CPU numeric profile x86-64-v4 the shipped conversion used): an
AVX2-only container raises and Modal retries on a fresh one.
Inputs: the DB1 through the job's pre-signed GET URL (never printed), the delivered source IFC + skipped_records.json from the
volume (/vol/<id>/source/, written by the src_db1 stage), the shipped STEP's parts.json through its GET URL.
Outputs: /vol/<id>/complete_db1/{model_completed.ifc, restoration_log.json, completed.stp(+.parts.json/.stats.json), complete_db1.log}

  .venv/bin/modal run complete/db1/modal_complete_db1.py --only n1,n2 [--no-step]"""
import json, os, shutil, sys, time, urllib.request, importlib.util

import modal

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(ROOT, 'src_db1')
VOL = '/vol'


def _build_image():
    p = os.path.join(SRC, 'modal_image.py')
    if not os.path.exists(p):
        return None
    spec = importlib.util.spec_from_file_location('pmp_src_db1_modal_image', p)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    img = mod.build(modal, SRC)
    for fn in ('regen_core.py', 'cpu_facts.py', 'stepcmp.py'):
        img = img.add_local_file(os.path.join(SRC, fn), f'/pmp/src_db1/{fn}')
    for fn in ('complete_core.py', 'ifc_canon.py'):
        img = img.add_local_file(os.path.join(HERE, fn), f'/pmp/complete_db1/{fn}')
    return img.add_local_dir(os.path.join(HERE, 'kit_g'), '/opt/kits/kit_g', ignore=['__pycache__'])


app = modal.App('pmp-complete-db1')
vol = modal.Volume.from_name('pmp-out')
image = _build_image()


class HostUnsuitable(RuntimeError):
    pass


def _get(url, dst):
    for k in range(5):
        try:
            with urllib.request.urlopen(url, timeout=600) as r, open(dst, 'wb') as f:
                shutil.copyfileobj(r, f, 1 << 22)
            return
        except Exception:
            if k == 4: raise
            time.sleep(3 * (k + 1))


@app.function(image=image, volumes={VOL: vol}, cpu=4.0, memory=32 * 1024, timeout=6 * 3600, single_use_containers=True,
              max_containers=4, retries=modal.Retries(max_retries=10, backoff_coefficient=1.0, initial_delay=1.0))
def complete(job: dict, do_step: bool = True) -> dict:
    sys.path.insert(0, '/pmp/src_db1')
    import cpu_facts, subprocess
    env = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}
    cf = cpu_facts.facts('/opt/conv/ifc84/bin/python', env)
    if not cf.get('avx512'):
        try:
            modal.experimental.stop_fetching_inputs()
        except Exception:
            pass
        raise HostUnsuitable(f"no AVX-512 ({cf.get('vendor')} {cf.get('family')}/{cf.get('model')})")
    mid = job['model_id']
    wd = f'/tmp/cdb1/{mid[:16]}'; shutil.rmtree(wd, ignore_errors=True); os.makedirs(wd)
    inp = os.path.join(wd, 'in'); os.makedirs(inp)
    _get(job['urls']['source'], os.path.join(inp, 'model.db1'))
    sp = None
    if job.get('_conv_parts_url'):
        sp = os.path.join(inp, 'shipped.stp.parts.json'); _get(job['_conv_parts_url'], sp)
    vol.reload()
    src = os.path.join(VOL, mid, 'source')
    for fn in ('model.ifc', 'skipped_records.json'):
        shutil.copyfile(os.path.join(src, fn), os.path.join(inp, fn))
    out = os.path.join(wd, 'out'); os.makedirs(out)
    jp = os.path.join(wd, 'job.json')
    json.dump({'model_id': mid, 'tag': job.get('tag'), 'db1': os.path.join(inp, 'model.db1'), 'orig_ifc': os.path.join(inp, 'model.ifc'),
               'skipped_records': os.path.join(inp, 'skipped_records.json'), 'orig_step_parts': sp, 'do_step': do_step}, open(jp, 'w'))
    t0 = time.time()
    r = subprocess.run(['/opt/conv/env/bin/python', '/pmp/complete_db1/complete_core.py', jp, os.path.join(wd, 'w'), out],
                       capture_output=True, text=True, env=env)
    tail = (r.stdout + r.stderr)[-3000:]
    dst = os.path.join(VOL, mid, 'complete_db1')
    shutil.rmtree(dst, ignore_errors=True); os.makedirs(dst)
    for fn in os.listdir(out):
        shutil.copyfile(os.path.join(out, fn), os.path.join(dst, fn))
    # the decoder outputs of both runs (for review): convert stats + restore events
    for k in ('base', 'comp'):
        for fn in ('convert.json', 'convert.json.restore.json'):
            p = os.path.join(wd, 'w', k, fn)
            if os.path.exists(p):
                shutil.copyfile(p, os.path.join(dst, f'{k}.{fn}'))
    vol.commit()
    lg = {}
    try:
        lg = json.load(open(os.path.join(out, 'restoration_log.json')))
    except Exception:
        pass
    return {'tag': job.get('tag'), 'rc': r.returncode, 'tail': tail, 'seconds': round(time.time() - t0, 1),
            'host': {k: cf.get(k) for k in ('vendor', 'family', 'model', 'numpy', 'openblas_core')},
            'files': sorted(os.listdir(dst)), 'verdict': lg.get('verdict'),
            'summary': {k: lg.get(k) for k in ('engine', 'control_kit_v_vs_source_ifc', 'comparison_completed_vs_source_ifc', 'untouched_parts_geometrically_identical',
                                               'decode', 'step', 'step_volume_check', 'guid_restore')}}


@app.local_entrypoint()
def main(only: str = 'n1,n2', no_step: bool = False, jobs: str = 'jobs/urls/new5.signed.jsonl'):
    allowed = {'992c3de413966850f7b95c8a089f22b74b446cfce41b5c6bef75427cbd7efd34', '4d188bbaad199b4772413ac8d76fd7e8e454c07e7a24da956a7f084efec6dd43'}
    rows = [json.loads(l) for l in open(os.path.join(ROOT, jobs)) if l.strip()]
    sel = [r for r in rows if any((r.get('tag') or '').startswith(o) for o in only.split(','))]
    for r in sel:
        if r['model_id'] not in allowed:
            raise SystemExit('refused: only n1 / n2 (the new DB1 samples)')
    import subprocess
    for r in sel:      # the shipped STEP's per-part table (conversion folder), pre-signed locally with the read-only profile (never printed)
        k = [f['key'] for f in r['conv']['files'] if f['key'].endswith('.u.stp.parts.json')][0]
        r['_conv_parts_url'] = subprocess.run(['aws', 's3', 'presign', f's3://bim-proprietary-data/{k}', '--expires-in', '86400'],
                                              capture_output=True, text=True, env=dict(os.environ, AWS_PROFILE='bim')).stdout.strip()
    calls = [(r, complete.spawn(r, not no_step)) for r in sel]
    os.makedirs(os.path.join(HERE, 'runs'), exist_ok=True)
    for r, c in calls:
        res = None
        for k in range(3):
            try:
                res = c.get(); break
            except Exception as e:
                res = {'tag': r['tag'], 'error': f'{type(e).__name__}: {str(e)[:400]}'}
                if 'AVX-512' not in str(e) and 'HostUnsuitable' not in type(e).__name__:
                    break
                c = complete.spawn(r, not no_step)
        json.dump(res, open(os.path.join(HERE, 'runs', f"{r['tag']}.json"), 'w'), indent=1, default=str)
        print(json.dumps(res, default=str)[:4000], flush=True)
