#!/usr/bin/env python3
"""Offline: Tekla-id join of every graded Windows-pipeline STEP (streamed from S3, never stored) with the grader's decoder
inventory (grade detail db1-<sha>.decoded_parts.json.gz). Writes wj/<sha12>.json. Read-only on bim."""
import os, sys, json, glob, gzip, subprocess, io, time
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'patch'))
import windows_join as wj
B = 'bim-proprietary-data'; DET = 'cad-disk-extract/zenitude-data-3/_state/conv/grade/detail'
ENV = dict(os.environ, AWS_PROFILE='bim')
os.makedirs(os.path.join(HERE, 'wj'), exist_ok=True)


def one(g):
    sha = g['sha256']; out = os.path.join(HERE, 'wj', sha[:12] + '.json')
    if os.path.exists(out):
        return sha[:12], 'cached'
    t0 = time.time()
    dp = os.path.join(HERE, 'detail', sha[:12] + '.decoded_parts.json.gz')
    if not os.path.exists(dp):
        subprocess.run(['aws', 's3', 'cp', f's3://{B}/{DET}/db1-{sha}.decoded_parts.json.gz', dp, '--only-show-errors'], env=ENV, check=True)
    parts = json.load(gzip.open(dp, 'rt'))
    p = subprocess.Popen(['aws', 's3', 'cp', f's3://{B}/{g["step_key"]}', '-'], env=ENV, stdout=subprocess.PIPE, bufsize=1 << 20)
    sc = wj.scan(io.TextIOWrapper(p.stdout, encoding='latin-1', newline=''))
    rc = p.wait()
    if rc != 0:
        return sha[:12], f'stream rc {rc}'
    ax = (g.get('redecode') or {}).get('axis_mismatch_dropped') or 0
    r = wj.join(sc, parts, ax)
    r['scan'] = {k: v for k, v in sc.items() if k != 'by_id'}
    r['step_key'] = g['step_key']; r['sec'] = round(time.time() - t0, 1)
    json.dump(r, open(out, 'w'))
    return sha[:12], f"ok {r['sec']}s cov={r['coverage']}"


if __name__ == '__main__':
    gs = [json.load(open(f)) for f in sorted(glob.glob(os.path.join(HERE, 'graderes', 'db1-*.json')))]
    gs = [g for g in gs if g.get('reuse_from') == 'disk-1/2-windows' and g.get('status') == 'ok']
    gs.sort(key=lambda g: (g.get('validate') or {}).get('step_bytes') or 0)
    with ThreadPoolExecutor(int(os.environ.get('PAR', '3'))) as ex:
        for sid, msg in ex.map(one, gs):
            print(sid, msg, flush=True)
