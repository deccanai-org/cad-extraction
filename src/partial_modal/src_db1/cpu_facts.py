"""cpu_facts.py - the CPU a container runs on, as the decoder / STEP stage see it (standard library only).

facts(py, env) -> {vendor, family, model, model_name, flags (SIMD subset), avx512 (bool: AVX-512 F/CD/BW/DQ/VL = the
SkylakeX level), numpy (SIMD targets numpy dispatches in the decoder venv), openblas_core (the kernel set numpy's bundled
OpenBLAS selected), error}. py = the decoder venv python (/opt/conv/ifc84/bin/python)."""
import json, subprocess

SIMD = ('sse4_2', 'avx', 'avx2', 'fma', 'avx512f', 'avx512cd', 'avx512bw', 'avx512dq', 'avx512vl', 'avx512ifma', 'avx512vbmi',
        'avx512_vnni', 'avx512_bf16', 'avx512_fp16', 'amx_tile')
SKX = ('avx512f', 'avx512cd', 'avx512bw', 'avx512dq', 'avx512vl')

PROBE = r'''
import json, ctypes, glob, os
import numpy
r = {}
try:
    from numpy._core._multiarray_umath import __cpu_features__ as f, __cpu_dispatch__ as d
    r['numpy'] = [k for k, v in f.items() if v and k in d]
except Exception as e:
    r['numpy'] = repr(e)
core = None
libs = glob.glob(os.path.join(os.path.dirname(numpy.__file__), '..', 'numpy.libs', '*openblas*'))
for p in libs:
    try:
        L = ctypes.CDLL(p)
    except OSError:
        continue
    for sym in ('scipy_openblas_get_corename64_', 'scipy_openblas_get_corename', 'openblas_get_corename64_', 'openblas_get_corename'):
        fn = getattr(L, sym, None)
        if fn is not None:
            fn.restype = ctypes.c_char_p
            core = fn().decode()
            break
    if core:
        break
r['openblas_core'] = core
r['openblas_lib'] = [os.path.basename(p) for p in libs]
print(json.dumps(r))
'''


def facts(py, env=None):
    out = {'vendor': None, 'family': None, 'model': None, 'model_name': None, 'flags': [], 'avx512': False}
    try:
        txt = open('/proc/cpuinfo').read()
        first = txt.split('\n\n')[0]
        kv = {}
        for line in first.splitlines():
            if ':' in line:
                k, v = line.split(':', 1)
                kv[k.strip()] = v.strip()
        out['vendor'] = kv.get('vendor_id')
        out['family'] = kv.get('cpu family')
        out['model'] = kv.get('model')
        out['model_name'] = kv.get('model name')
        fl = set(kv.get('flags', '').split())
        out['flags'] = [x for x in SIMD if x in fl]
        out['avx512'] = all(x in fl for x in SKX)
    except Exception as e:
        out['error'] = f'cpuinfo: {type(e).__name__}: {e}'
    try:
        r = subprocess.run([py, '-c', PROBE], capture_output=True, text=True, env=env, timeout=120)
        out.update(json.loads(r.stdout.strip().splitlines()[-1]))
    except Exception as e:
        out['error'] = (out.get('error', '') + f' numpy probe: {type(e).__name__}: {e}').strip()
    return out
