"""Modal unit test of the standards library + the standards patches (app pmp-standards-test, workspace navaneeth).

    .venv/bin/modal run complete/standards/modal_test.py

The image is the pipeline image (python 3.11 + code/requirements.txt: build123d 0.13.0, cadquery-ocp-novtk 8.0.1.1.0,
the same pins as the shipped scripts). The baseline bounding boxes of the replaced parts (issues.json) are passed in, so
the test also checks that every replacement stays inside the envelope it replaces. Results -> out/modal_test_result.json.
"""
import json
import os
import pathlib

import modal

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SYS_LIBS = ['libgl1', 'libxrender1', 'libxext6', 'libsm6', 'libfontconfig1', 'libxkbcommon0', 'libxi6']

image = (modal.Image.debian_slim(python_version='3.11')
         .apt_install(*SYS_LIBS)
         .pip_install_from_requirements(str(ROOT / 'code' / 'requirements.txt'))
         .env({'PYTHONUNBUFFERED': '1', 'OMP_NUM_THREADS': '1'})
         .add_local_dir(HERE / 'steelstd', '/std/steelstd', ignore=['__pycache__'])
         .add_local_dir(HERE / 'tests', '/std/tests', ignore=['__pycache__'])
         .add_local_dir(HERE / 'out', '/std/out', ignore=['modal_test_result.json']))

app = modal.App('pmp-standards-test', image=image)


@app.function(cpu=4.0, memory=8192, timeout=3600)
def run_tests(baselines: dict):
    import sys
    import time
    sys.path.insert(0, '/std')
    sys.path.insert(0, '/std/tests')
    import build123d
    import test_steelstd
    t = time.time()
    r = test_steelstd.main('/std/out', baselines)
    r['seconds'] = round(time.time() - t, 1)
    r['build123d'] = build123d.__version__ if hasattr(build123d, '__version__') else 'unknown'
    return r


@app.local_entrypoint()
def main():
    import sys
    sys.path.insert(0, str(ROOT / 'complete' / 'integrate'))
    from samples import baseline_tree
    baselines = {}
    for tag in os.listdir(HERE / 'out'):
        bt = baseline_tree(tag) if (HERE / 'out' / tag / 'patch.json').exists() else None
        if bt:
            iss = json.load(open(os.path.join(bt, 'schedules', 'issues.json')))
            baselines[tag] = {pid: p.get('bbox') for pid, p in iss['parts'].items() if p.get('bbox')}
    r = run_tests.remote(baselines)
    (HERE / 'out' / 'modal_test_result.json').write_text(json.dumps(r, indent=1))
    print(f"{r['passed']}/{r['total']} passed in {r['seconds']} s (build123d {r['build123d']})")
    for f in r['failed'][:40]:
        print('FAIL', f['test'], f['detail'][:300])
