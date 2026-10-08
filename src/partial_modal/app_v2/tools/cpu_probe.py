"""cpu_probe.py - which CPU features do Modal containers get (no data, no model)?
  .venv/bin/modal run app/tools/cpu_probe.py
"""
import json

import modal

app = modal.App('pmp-cpuprobe')
img = modal.Image.debian_slim(python_version='3.11').pip_install('numpy==2.4.6')


@app.function(image=img, cpu=1.0, memory=1024, max_containers=8)
def facts(i: int):
    import os, subprocess, time
    txt = open('/proc/cpuinfo').read()
    fl = next((l for l in txt.splitlines() if l.startswith('flags')), '').split()
    model = next((l.split(':', 1)[1].strip() for l in txt.splitlines() if l.startswith('model name')), None)
    r = subprocess.run(['python', '-c', 'import json; from numpy._core._multiarray_umath import __cpu_features__ as f, '
                        '__cpu_dispatch__ as d; print(json.dumps([k for k,v in f.items() if v and k in d]))'],
                       capture_output=True, text=True)
    time.sleep(2)
    return dict(i=i, model=model, avx512=sorted(x for x in fl if x.startswith('avx512'))[:6], n_flags=len(fl),
                numpy=r.stdout.strip(), cloud=os.environ.get('MODAL_CLOUD_PROVIDER'), region=os.environ.get('MODAL_REGION'))


@app.local_entrypoint()
def main(n: int = 8):
    for r in facts.map(range(n)):
        print(json.dumps(r))
