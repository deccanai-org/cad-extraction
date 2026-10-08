"""cpu_census.py - which CPUs do Modal CPU containers land on, per cloud? (no data, no model; reads /proc/cpuinfo only)

The src_db1 reproduction needs an AVX-512 host (see README "CPU requirement"). Placement cannot be pinned in this
workspace (Modal refuses cloud='aws' and cloud='gcp': "Pinning cloud ... not supported"), so this only measures how
often an unpinned CPU container lands on an AVX-512 host (= how many retries the stage needs on average).
  .venv/bin/modal run src_db1/tests/cpu_census.py --n 8
"""
import json, os, time

import modal

app = modal.App('pmp-src-db1-cpucensus')
img = modal.Image.debian_slim(python_version='3.11')


def _facts(i):
    txt = open('/proc/cpuinfo').read()
    kv = {}
    for line in txt.split('\n\n')[0].splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            kv[k.strip()] = v.strip()
    fl = set(kv.get('flags', '').split())
    time.sleep(25)                     # keep the container busy so parallel inputs land on separate containers
    return dict(i=i, vendor=kv.get('vendor_id'), family=kv.get('cpu family'), model=kv.get('model'),
                avx512=all(x in fl for x in ('avx512f', 'avx512cd', 'avx512bw', 'avx512dq', 'avx512vl')),
                cloud=os.environ.get('MODAL_CLOUD_PROVIDER'), region=os.environ.get('MODAL_REGION'),
                task=os.environ.get('MODAL_TASK_ID'))


@app.function(image=img, cpu=1.0, memory=512, max_containers=10)
def auto(i: int):
    return _facts(i)


REGION = os.environ.get('PMP_CENSUS_REGION', 'ap-southeast')


@app.function(image=img, cpu=1.0, memory=512, max_containers=10, region=REGION)
def region(i: int):
    return _facts(i)


@app.local_entrypoint()
def main(n: int = 10, which: str = 'auto'):
    out = {}
    for name in which.split(','):
        fn = {'auto': auto, 'region': region}[name]
        rows = list(fn.map(range(n)))
        out[name] = rows
        for r in rows:
            print(name, json.dumps(r), flush=True)
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results', 'cpu_census.json')
    os.makedirs(os.path.dirname(p), exist_ok=True)
    old = {}
    if os.path.exists(p):
        try:
            old = json.load(open(p))
        except Exception:
            old = {}
    for k, v in out.items():
        old.setdefault(k, []).extend(v)
    json.dump(old, open(p, 'w'), indent=1)
