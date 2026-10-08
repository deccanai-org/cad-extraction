#!/usr/bin/env python3
"""make_tasks.py -> tasks_main.json + equiv specs for the box run (BOX-A, /work/agentwork/step-verify-big).
Phase 1  equivalence on 3 medium STEP files: 3 full read-backs each (step_check.py, the grader's tool) + streamed runs at 2 MB and
         24 MB chunks (grader settings: --max-check 150000), compared root by root, plus the grader's stored read-back
Phase 2  models graded not_read_back_large_file: 4 below 1 GB (memory-killed on the grader boxes) with a full reference read on
         this box, 1 above 1 GB with a full reference read (and step_check's sampling emulated), the largest (8.8 GB) streamed only
Phase 3  the other flagged models that have a source inventory: streamed (exact) + final-pass readback record with the join"""
import json, os, sys

H = os.path.dirname(os.path.abspath(__file__))
PY = '/opt/conv/env/bin/python'
B = 'bim-proprietary-data'
ST = 'cad-disk-extract/zenitude-data-3/_state/conv'
LL = json.load(open(os.path.join(H, '..', 'data', 'large_list.json')))
byid = {x['id']: x for x in LL}
tasks = []


def T(name, cmd, threads=1, mem=2, deps=(), outputs=()):
    tasks.append({'name': name, 'cmd': cmd, 'threads': threads, 'mem_gb': mem, 'deps': list(deps), 'outputs': list(outputs)})


def fetch(tag, step_key, refs=(), sha=True):
    c = [f'mkdir -p in ref out/{tag}',
         f'aws s3 cp --only-show-errors s3://{B}/{step_key} in/{tag}.step',
         f'aws s3api head-object --bucket {B} --key {step_key} > ref/{tag}.head.json']
    if sha:
        c.append(f'sha256sum in/{tag}.step > ref/{tag}.sha256')
    for k, dst in refs:
        c.append(f'(aws s3 cp --only-show-errors s3://{B}/{k} ref/{dst} || echo "missing {k}")')
    T(f'fetch_{tag}', ' && '.join(c), 1, 1, (), [f'ref/{tag}.head.json'] + ([f'ref/{tag}.sha256'] if sha else []))


def full(tag, lab, mem=4, extra=''):
    o = f'out/{tag}/full_{lab}'
    T(f'full_{tag}_{lab}', f'{PY} pkg/step_check.py in/{tag}.step {o}.json --parts {o}.parts.jsonl.gz {extra} > {o}.log 2>&1',
      1, mem, [f'fetch_{tag}'], [f'{o}.json', f'{o}.parts.jsonl.gz', f'{o}.log'])


def stream(tag, lab, chunk, workers, mem, maxcheck, deps=()):
    o = f'out/{tag}/s_{lab}'
    T(f's_{tag}_{lab}', f'{PY} pkg/step_verify_big.py in/{tag}.step {o}.json --parts {o}.parts.jsonl.gz --chunk-mb {chunk} '
                        f'--workers {workers} --mem-gb {mem} --max-check {maxcheck} --workdir wd/{tag}_{lab} > {o}.log 2>&1',
      workers + 1, mem, [f'fetch_{tag}'] + list(deps), [f'{o}.json', f'{o}.parts.jsonl.gz', f'{o}.log'])


def final_rec(tag, mid, step_key, src_ref, lab, deps):
    o = f'out/{tag}/final_readback_{lab}.json'
    T(f'final_{tag}_{lab}', f'{PY} pkg/to_final_result.py out/{tag}/s_{lab}.json out/{tag}/s_{lab}.parts.jsonl.gz --pipeline ifc '
                            f'--model-id {mid} --step-key {step_key} --src-parts ref/{src_ref} --grade-join pkg/grade_join.py -o {o} > {o}.log 2>&1',
      1, 1, deps, [o, o + '.log'])


spec1, spec2 = {}, {}
BIG = sorted([x for x in LL if x['step_bytes'] >= 1 << 30], key=lambda x: x['step_bytes'])
b1, b2 = BIG[0], BIG[-1]
fetch('B1', b1['step_key'])
full('B1', 'a', 32)                                # step_check defaults (max-check 150000): the grader's exact settings
# ------------------------------------------------------------------ phase 1: medium files
MED = [('m1', 'cad-disk-extract/zenitude-data-3/conversions/ifc-step/0cfccd094e0dfee5d30460b38878163d8b1f2d6f62a2accb97ae6b565f59ea6b.step',
        'pkg/ref_m1.result.json', 'pkg/ref_m1.ec2.step_parts.jsonl.gz', 4),
       ('m2', 'cad-disk-extract/conversions/ifc-step/a78a529631779c987db44da5bf6e5bdb_8008691.stp',
        'pkg/ref_m2.result.json', 'pkg/ref_m2.ec2.step_parts.jsonl.gz', 4),
       ('m3', 'cad-disk-extract/zenitude-data-3/conversions/db1-step/863be0aa5b95f0f165f6026c5d78c9db7fc3d78e8f536f075042989bd1347f9b.stp',
        'pkg/ref_m3.result.json', 'pkg/ref_m3.ec2.step_parts.jsonl.gz', 8)]
for tag, key, rj, rp, mem in MED:
    fetch(tag, key)
    for lab in 'abc':
        full(tag, lab, mem)
    stream(tag, 'c2', 2, 6, 8, 150000)
    stream(tag, 'c24', 24, 3, 8, 150000)
    spec1[tag] = {'full': [[f'out/{tag}/full_{l}.json', f'out/{tag}/full_{l}.parts.jsonl.gz', f'full_{l}'] for l in 'abc'],
                  'ec2': [rj, rp, 'grader_ec2'],
                  'stream': [[f'out/{tag}/s_{l}.json', f'out/{tag}/s_{l}.parts.jsonl.gz', f's_{l}'] for l in ('c2', 'c24')]}
p1 = [t['name'] for t in tasks if not t['name'].startswith('fetch')]
T('equiv_p1', f'{PY} pkg/equiv_summary.py pkg/spec_p1.json out/equiv_p1.json > out/equiv_p1.txt 2>&1', 1, 2, p1,
  ['out/equiv_p1.json', 'out/equiv_p1.txt'])

# ------------------------------------------------------------------ phase 2: flagged models
FL = [('L1', '68648146cf8c324b302bbf3d02265deebde5866376f0dde28b479f847fc1cd5b', 12),
      ('L2', 'b9e5ef0ad07bd8c300a8a0ae132e68db1fe0597d50824d798414a245e4c79b4e', 12),
      ('F1', '83264a1d74d07d7a2d1eed7aa28cb04216691d05432fecefa701af5a94ffa097', 6),
      ('F2', '8c5c3e0614479b76200cbfb63be88bcf3355864f2c8ca86bae4ca0145be8868b', 6)]
for tag, mid, mem in FL:
    x = byid[mid]
    fetch(tag, x['step_key'], [(f'{ST}/ifc/detail/{mid}.step_parts.jsonl.gz', f'{tag}.ec2.step_parts.jsonl.gz'),
                               (f'{ST}/ifc/detail/{mid}.src_parts.jsonl.gz', f'{tag}.src_parts.jsonl.gz'),
                               (f'{ST}/ifc/results/{mid}.json', f'{tag}.result.json')])
    full(tag, 'a', mem)
    stream(tag, 'x24', 24, 6, 12, 0)               # exact (every solid checked): the deliverable run
    final_rec(tag, mid, x['step_key'], f'{tag}.src_parts.jsonl.gz', 'x24', [f's_{tag}_x24', f'fetch_{tag}'])
    spec2[tag] = {'full': [[f'out/{tag}/full_a.json', f'out/{tag}/full_a.parts.jsonl.gz', 'full_a']],
                  'ec2': ['-', f'ref/{tag}.ec2.step_parts.jsonl.gz', 'grader_ec2_parts'],
                  'stream': [[f'out/{tag}/s_x24.json', f'out/{tag}/s_x24.parts.jsonl.gz', 's_x24']]}
# > 1 GB: the smallest (full reference fits this box, started first above) and the largest
stream('B1', 'g24', 24, 8, 16, 150000)             # same sampling as step_check's default, emulated in global root order
spec2['B1'] = {'full': [['out/B1/full_a.json', 'out/B1/full_a.parts.jsonl.gz', 'full_a']],
               'stream': [['out/B1/s_g24.json', 'out/B1/s_g24.parts.jsonl.gz', 's_g24']]}
fetch('B2', b2['step_key'])
stream('B2', 'x24', 24, 12, 24, 0)
p2 = [t['name'] for t in tasks if t['name'].split('_')[1][:2] in ('L1', 'L2', 'F1', 'F2', 'B1') and not t['name'].startswith(('fetch', 'final'))]
T('equiv_p2', f'{PY} pkg/equiv_summary.py pkg/spec_p2.json out/equiv_p2.json > out/equiv_p2.txt 2>&1', 1, 2, p2,
  ['out/equiv_p2.json', 'out/equiv_p2.txt'])

# ------------------------------------------------------------------ phase 3: the other flagged models with a source inventory
done = {mid for _, mid, _ in FL}
P3 = sorted([x for x in LL if x['id'] not in done and 'source_inventory_unavailable' not in x['issues']], key=lambda x: x['step_bytes'])
p3 = []
for n, x in enumerate(P3):
    tag = f'P{n:02d}_{x["id"][:8]}'
    fetch(tag, x['step_key'], [(f'{ST}/ifc/detail/{x["id"]}.src_parts.jsonl.gz', f'{tag}.src_parts.jsonl.gz'),
                               (f'{ST}/ifc/detail/{x["id"]}.step_parts.jsonl.gz', f'{tag}.ec2.step_parts.jsonl.gz')], sha=False)
    stream(tag, 'x24', 24, 4, 8, 0)
    final_rec(tag, x['id'], x['step_key'], f'{tag}.src_parts.jsonl.gz', 'x24', [f's_{tag}_x24', f'fetch_{tag}'])
    T(f'clean_{tag}', f'rm -f in/{tag}.step', 1, 0, [f'final_{tag}_x24'])
    p3.append(tag)

json.dump(tasks, open(os.path.join(H, 'tasks_main.json'), 'w'), indent=1)
json.dump(spec1, open(os.path.join(H, 'spec_p1.json'), 'w'), indent=1)
json.dump(spec2, open(os.path.join(H, 'spec_p2.json'), 'w'), indent=1)
json.dump({'phase3': [{'tag': t, 'id': x['id'], 'step_key': x['step_key'], 'step_bytes': x['step_bytes'], 'issues': x['issues']}
                      for t, x in zip(p3, P3)],
           'B1': {'id': b1['id'], 'step_key': b1['step_key'], 'step_bytes': b1['step_bytes']},
           'B2': {'id': b2['id'], 'step_key': b2['step_key'], 'step_bytes': b2['step_bytes']},
           'flagged': {t: mid for t, mid, _ in FL}}, open(os.path.join(H, 'targets.json'), 'w'), indent=1)
print(len(tasks), 'tasks;', 'phase3 models', len(P3), 'GB', round(sum(x['step_bytes'] for x in P3) / 2**30, 1), '| B1', b1['id'][:12],
      round(b1['step_bytes'] / 2**20), 'MB | B2', b2['id'][:12], round(b2['step_bytes'] / 2**20), 'MB')
