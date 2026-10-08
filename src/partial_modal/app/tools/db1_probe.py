"""db1_probe.py - why does the DB1 regeneration not reproduce the shipped STEP on Modal? (diagnostic, new samples only)

Runs kit_v's convert_one + ifc2step6 on ONE new DB1 sample under several environment variants and compares each STEP with
the shipped STEP (stepcmp). Reports the container CPU and numpy SIMD dispatch.

  .venv/bin/modal run app/tools/db1_probe.py --tag n1_db1_small
"""
import json, os, pathlib, subprocess, sys, time

import modal

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / 'src_db1'))

app = modal.App('pmp-db1probe')
vol = modal.Volume.from_name('pmp-out', create_if_missing=True)


def _image():
    import importlib.util
    spec = importlib.util.spec_from_file_location('mi', ROOT / 'src_db1' / 'modal_image.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    img = m.build(modal, ROOT / 'src_db1')
    for f in ('stepcmp.py',):
        img = img.add_local_file(ROOT / 'src_db1' / f, f'/pmp/src_db1/{f}')
    return img


AVX512 = 'AVX512F AVX512CD AVX512_KNL AVX512_KNM AVX512_SKX AVX512_CLX AVX512_CNL AVX512_ICL AVX512_SPR AVX512_SPR_FP16'


@app.function(image=_image() if modal.is_local() else modal.Image.debian_slim(), cpu=4.0, memory=16384, timeout=3600, volumes={'/vol': vol})
def probe(urls: dict, variants: list, cloud_note: str = ''):
    import hashlib, shutil, urllib.request
    out = {'cpu': None, 'flags': None, 'numpy': None, 'variants': {}}
    try:
        txt = open('/proc/cpuinfo').read()
        out['cpu'] = next((l.split(':', 1)[1].strip() for l in txt.splitlines() if l.startswith('model name')), None)
        fl = next((l for l in txt.splitlines() if l.startswith('flags')), '')
        out['flags'] = sorted(x for x in fl.split() if x in ('avx2', 'fma', 'avx512f', 'avx512_bf16', 'amx_tile', 'avx512vl'))
    except Exception as e:
        out['cpu'] = repr(e)
    env0 = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'VIRTUAL_ENV', 'CONDA'))}
    r = subprocess.run(['/opt/conv/ifc84/bin/python', '-c', 'import numpy, json; from numpy._core._multiarray_umath import '
                        '__cpu_features__ as f, __cpu_dispatch__ as d; print(json.dumps([k for k,v in f.items() if v and k in d]))'],
                       capture_output=True, text=True, env=env0)
    out['numpy'] = (r.stdout + r.stderr).strip()[-600:]
    out['glibc'] = open('/opt/glibc.version').read().strip() if os.path.exists('/opt/glibc.version') else 'debian'
    w = '/tmp/probe'
    shutil.rmtree(w, ignore_errors=True)
    os.makedirs(w)
    for k, n in (('source', 'in.db1'), ('step', 'shipped.step')):
        with urllib.request.urlopen(urls[k], timeout=120) as f, open(f'{w}/{n}', 'wb') as g:
            shutil.copyfileobj(f, g)
    kd = '/opt/kits/kit_v'
    L = json.load(open(f'{kd}/layouts.json'))
    import re, zlib
    raw = open(f'{w}/in.db1', 'rb').read(1 << 16)
    data = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw) if raw[:2] == b'\x1f\x8b' else raw
    eng = re.search(rb'(\d+\.\d+)', data[:16]).group(1).decode()
    json.dump(L[eng]['layout'], open(f'{w}/layout.json', 'w'))
    json.dump([v['layout'] for v in L.values() if v.get('layout')], open(f'{w}/variants.json', 'w'))
    for name, extra, drop in variants:
        vd = f'{w}/{name}'
        os.makedirs(f'{vd}/tmp')
        os.link(f'{w}/in.db1', f'{vd}/in.db1')
        env = dict(env0, TMPDIR=f'{vd}/tmp', V6_FAR_VERIFY='0', PYTHONNOUSERSITE='1')
        env.update(extra)
        for d in drop:
            env.pop(d, None)
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
            c = {k: c.get(k) for k in ('diff_lines', 'identical_modulo_ids', 'products', 'lines')}
        except Exception:
            c = {'error': (r3.stdout + r3.stderr)[-500:]}
        ifc_sha = hashlib.sha256(open(f'{vd}/model.ifc', 'rb').read()).hexdigest() if os.path.exists(f'{vd}/model.ifc') else None
        out['variants'][name] = dict(cmp=c, rc=(r1.returncode, r2.returncode), sec=round(time.time() - t0, 1),
                                     step_bytes=os.path.getsize(f'{vd}/model.stp') if os.path.exists(f'{vd}/model.stp') else None,
                                     ifc_sha=ifc_sha[:12] if ifc_sha else None, err=(r1.stderr + r2.stderr)[-300:] if (r1.returncode or r2.returncode) else None)
        print(name, json.dumps(out['variants'][name]), flush=True)
        os.makedirs('/vol/_diag/n1', exist_ok=True)
        for fn in ('model.ifc', 'model.stp', 'convert.json'):
            if os.path.exists(f'{vd}/{fn}'):
                shutil.copyfile(f'{vd}/{fn}', f'/vol/_diag/n1/{name}_{fn}')
        vol.commit()
    return out


@app.local_entrypoint()
def main(tag: str = 'n1_db1_small', which: str = 'all'):
    allowed = {r['tag'] for r in json.loads((ROOT / 'new5.json').read_text()) if r['step_source'] == 'db1'}
    if tag not in allowed:
        raise SystemExit('only the new DB1 samples')
    rows = [json.loads(l) for l in open(ROOT / 'jobs' / 'urls' / 'new5.signed.jsonl')]
    r = [x for x in rows if x['tag'] == tag][0]
    V = [('base', {'PYTHONHASHSEED': '0'}, []),
         ('nohash', {}, ['PYTHONHASHSEED']),
         ('npy_no512', {'PYTHONHASHSEED': '0', 'NPY_DISABLE_CPU_FEATURES': AVX512}, []),
         ('blas_spr', {'PYTHONHASHSEED': '0', 'OPENBLAS_CORETYPE': 'SAPPHIRERAPIDS'}, []),
         ('blas_skx', {'PYTHONHASHSEED': '0', 'OPENBLAS_CORETYPE': 'SKYLAKEX'}, []),
         ('blas_hsw', {'PYTHONHASHSEED': '0', 'OPENBLAS_CORETYPE': 'HASWELL'}, []),
         ('base2', {'PYTHONHASHSEED': '0'}, [])]
    if which == 'base':
        V = [V[0], V[1]]
    res = probe.remote({'source': r['urls']['source'], 'step': r['urls']['step']}, V)
    print(json.dumps(res, indent=1))
    (HERE / 'db1_probe_result.json').write_text(json.dumps(res, indent=1))


@app.function(image=(_image().add_local_file(HERE / 'kdump.py', '/pmp/tools/kdump.py')) if modal.is_local() else modal.Image.debian_slim(),
              cpu=4.0, memory=8192, timeout=1800, volumes={'/vol': vol})
def kdump(ifc_on_vol: str):
    env0 = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'VIRTUAL_ENV', 'CONDA'))}
    r = subprocess.run(['/opt/conv/ifc84/bin/python', '/pmp/tools/kdump.py', ifc_on_vol, '/tmp/kd.json', '4'],
                       capture_output=True, text=True, env=env0)
    return {'rc': r.returncode, 'tail': (r.stdout + r.stderr)[-500:], 'res': json.load(open('/tmp/kd.json')) if r.returncode == 0 else None}


@app.local_entrypoint()
def kd():
    r = kdump.remote('/vol/_diag/n1/base_model.ifc')
    (HERE / 'kdump_modal_n1.json').write_text(json.dumps(r['res'], sort_keys=True))
    print(r['rc'], r['tail'])
