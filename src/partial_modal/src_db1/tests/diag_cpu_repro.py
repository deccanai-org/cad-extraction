"""diag_cpu_repro.py - does the DB1 -> IFC -> STEP regeneration depend on the CPU the Modal container lands on?
(diagnostic for the src_db1 stage; NEW sample n1 only)

Runs the pinned kit (kit_v) decoder + STEP stage on new sample n1 in N containers at once, each under several numeric-
kernel variants, and compares every STEP with the shipped STEP (stepcmp). Records per container: CPU vendor / family /
model / AVX-512 flags, numpy's dispatched SIMD targets, the OpenBLAS core numpy's bundled OpenBLAS picked.

  .venv/bin/modal run src_db1/tests/diag_cpu_repro.py --n 6
Writes src_db1/tests/results/diag_cpu_repro.json (no URLs)."""
import json, os, pathlib, subprocess, sys, time

import modal

HERE = pathlib.Path(__file__).resolve().parent
COMP = HERE.parent
ROOT = COMP.parent
sys.path.insert(0, str(COMP))

app = modal.App('pmp-src-db1-diag')


def _image():
    import importlib.util
    spec = importlib.util.spec_from_file_location('mi', COMP / 'modal_image.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    img = m.build(modal, COMP)
    return img.add_local_file(COMP / 'stepcmp.py', '/pmp/src_db1/stepcmp.py').add_local_file(
        COMP / 'cpu_facts.py', '/pmp/src_db1/cpu_facts.py')


NO_V4 = 'X86_V4 AVX512_ICL AVX512_SPR'
VARIANTS = [
    ('base', {}),
    ('blas_haswell', {'OPENBLAS_CORETYPE': 'Haswell'}),
    ('npy_no_v4', {'NPY_DISABLE_CPU_FEATURES': NO_V4}),
    ('blas_skx', {'OPENBLAS_CORETYPE': 'SkylakeX'}),          # only where the CPU has AVX-512
    ('blas_skx_npy_no_v4', {'OPENBLAS_CORETYPE': 'SkylakeX', 'NPY_DISABLE_CPU_FEATURES': NO_V4}),
]


@app.function(image=_image() if modal.is_local() else modal.Image.debian_slim(), cpu=4.0, memory=16384, timeout=3600,
              max_containers=10)
def one(i: int, urls: dict):
    import hashlib, re, shutil, urllib.request, zlib
    sys.path.insert(0, '/pmp/src_db1')
    import cpu_facts
    env0 = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'VIRTUAL_ENV', 'CONDA'))}
    env0.update(PYTHONHASHSEED='0', PYTHONNOUSERSITE='1', V6_FAR_VERIFY='0')
    out = {'i': i, 'cpu': cpu_facts.facts('/opt/conv/ifc84/bin/python', env0), 'variants': {},
           'modal': {k: os.environ.get(k) for k in ('MODAL_CLOUD_PROVIDER', 'MODAL_REGION', 'MODAL_TASK_ID')}}
    w = f'/tmp/diag{i}'
    shutil.rmtree(w, ignore_errors=True)
    os.makedirs(w)
    for k, n in (('db1', 'in.db1'), ('step', 'shipped.step')):
        with urllib.request.urlopen(urls[k], timeout=120) as f, open(f'{w}/{n}', 'wb') as g:
            shutil.copyfileobj(f, g)
    kd = '/opt/kits/kit_v'
    L = json.load(open(f'{kd}/layouts.json'))
    raw = open(f'{w}/in.db1', 'rb').read(1 << 16)
    data = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw) if raw[:2] == b'\x1f\x8b' else raw
    eng = re.search(rb'(\d+\.\d+)', data[:16]).group(1).decode()
    json.dump(L[eng]['layout'], open(f'{w}/layout.json', 'w'))
    json.dump([v['layout'] for v in L.values() if v.get('layout')], open(f'{w}/variants.json', 'w'))
    avx512 = 'avx512f' in (out['cpu'].get('flags') or [])
    for name, extra in VARIANTS:
        if 'SkylakeX' in extra.get('OPENBLAS_CORETYPE', '') and not avx512:
            out['variants'][name] = 'n/a (no AVX-512 on this CPU)'
            continue
        vd = f'{w}/{name}'
        os.makedirs(f'{vd}/tmp')
        os.link(f'{w}/in.db1', f'{vd}/in.db1')
        env = dict(env0, TMPDIR=f'{vd}/tmp', **extra)
        t0 = time.time()
        r1 = subprocess.run(['/opt/conv/ifc84/bin/python', f'{kd}/convert_one.py', f'{vd}/in.db1', f'{vd}/model.ifc',
                             f'{kd}/tekla_profiles.json', f'{w}/layout.json', f'{vd}/convert.json', f'{w}/variants.json'],
                            capture_output=True, text=True, env=env, cwd=vd)
        r2 = subprocess.run(['/opt/conv/ifc84/bin/python', f'{kd}/ifc2step6.py', f'{vd}/model.ifc', f'{vd}/model.stp', '--mode',
                             'hybrid', '--prec', '2', '--threads', '4'], capture_output=True, text=True, env=env, cwd=vd)
        r3 = subprocess.run(['/opt/conv/env/bin/python', '/pmp/src_db1/stepcmp.py', f'{vd}/model.stp', f'{w}/shipped.step'],
                            capture_output=True, text=True, env=env0)
        try:
            c = json.loads(r3.stdout.strip().splitlines()[-1])
            c = {k: c.get(k) for k in ('diff_lines', 'identical_modulo_ids', 'products')}
        except Exception:
            c = {'error': (r3.stdout + r3.stderr)[-300:]}
        # IFC content hash without the wall-clock lines (FILE_NAME, IfcOwnerHistory) and GlobalIds (random)
        h = hashlib.sha256()
        if os.path.exists(f'{vd}/model.ifc'):
            for line in open(f'{vd}/model.ifc', 'rb'):
                if line.startswith(b'FILE_NAME(') or b'=IFCOWNERHISTORY(' in line[:30]:
                    continue
                h.update(re.sub(rb"\('[0-9A-Za-z_$]{22}'", b"('G'", line))
        out['variants'][name] = dict(cmp=c, rc=(r1.returncode, r2.returncode), sec=round(time.time() - t0, 1),
                                     ifc_content=h.hexdigest()[:12],
                                     err=(r1.stderr + r2.stderr)[-300:] if (r1.returncode or r2.returncode) else None)
    return out


@app.local_entrypoint()
def main(n: int = 6):
    allowed = {r['model_id'] for r in json.load(open(ROOT / 'new5.json'))}
    J = json.load(open(HERE / 'jobs_n1n2.urls.json'))
    j = [x for x in J if x['tag'].startswith('n1')][0]
    assert j['model_id'] in allowed
    urls = {'db1': j['urls']['db1'], 'step': j['urls']['step']}
    res = []
    for r in one.starmap([(i, urls) for i in range(n)]):
        res.append(r)
        print(json.dumps({'i': r['i'], 'cpu': {k: r['cpu'].get(k) for k in ('vendor', 'family', 'model', 'avx512', 'numpy', 'openblas_core')},
                          'modal': r['modal'], 'v': {k: (v if isinstance(v, str) else [v['cmp'].get('diff_lines'), v['ifc_content']])
                                                     for k, v in r['variants'].items()}}), flush=True)
    os.makedirs(HERE / 'results', exist_ok=True)
    (HERE / 'results' / 'diag_cpu_repro.json').write_text(json.dumps(res, indent=1))
