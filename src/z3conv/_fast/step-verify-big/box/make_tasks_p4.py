#!/usr/bin/env python3
"""make_tasks_p4.py INDEX.jsonl.gz [--shard K/N] [--workers 6] -> p4_targets.json + tasks_p4[_K_of_N].json
Phase 4 = every IFC model the CURRENT index still tags not_read_back_large_file / not_read_back_out_of_memory, at the STEP it is
graded from now (index step_key), minus those already covered by an applicable record. Order: models with no other blocking
issue (class-1 candidates once the read-back is clean) first, smallest first; then the rest. Per model: fetch STEP + src_parts
(coord/build_index.py detail_keys) -> streamed read-back (exact, nice 19) -> final-pass record with the join -> record + parts
uploaded at once to agentwork/step-verify-big/final/{results,detail}/ -> STEP copy deleted. A sliding window keeps at most 4
STEP copies on disk. Shards split the list round-robin so several boxes can share it."""
import json, os, sys, gzip, argparse

H = os.path.dirname(os.path.abspath(__file__))
PY = '/opt/conv/env/bin/python'
B = 'bim-proprietary-data'
ST = 'cad-disk-extract/zenitude-data-3/_state/conv'
OUT = 's3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/step-verify-big/final'
READ_TAGS = ('not_read_back_large_file', 'not_read_back_out_of_memory', 'per_part_verification_pending')
ap = argparse.ArgumentParser(); ap.add_argument('index'); ap.add_argument('--shard', default='1/1'); ap.add_argument('--workers', type=int, default=6)
ap.add_argument('--covered', default=os.path.join(H, 'covered.json'), help='{id: step_key} of applicable records already made')
a = ap.parse_args()
k, n = (int(x) for x in a.shard.split('/'))
rows = [json.loads(l) for l in gzip.open(a.index, 'rt') if l.strip()]
covered = json.load(open(a.covered)) if os.path.exists(a.covered) else {}
ap2 = os.path.join(H, 'p4_done_ids.json')                  # ids (first 40 chars) with a phase-4 record already in final/results
done40 = set(json.load(open(ap2))) if os.path.exists(ap2) else set()


def detail_src(r):
    """source inventory keys of the model, most specific first: a converter re-run writes its detail with the STEP's suffix
    (<id>.v6.step -> ifc/detail/<id>.v6.src_parts.jsonl.gz; coord/build_index.py detail_keys does not know it), then
    detail_keys' own choice"""
    out = []
    base = r['step_key'].rsplit('/', 1)[-1]
    if base.startswith(r['id']) and base.endswith('.step') and len(base) > len(r['id']) + 5:
        out.append(f'{ST}/{r["pipeline"]}/detail/{r["id"]}{base[len(r["id"]):-5]}.src_parts.jsonl.gz')
    if r.get('detail_prefix'):
        out.append(r['detail_prefix'] + '.src_parts.jsonl.gz')
    elif r.get('reused'):
        out.append(f'{ST}/grade/detail/{r["pipeline"]}-{r["id"]}.src_parts.jsonl.gz')
    else:
        out.append(f'{ST}/{r["pipeline"]}/detail/{r["id"]}.src_parts.jsonl.gz')
    return out


tg = []
for r in rows:
    iss = [str(i) for i in (r.get('issues') or [])]
    if r['pipeline'] != 'ifc' or not r.get('step_key') or not any(i.startswith(READ_TAGS[:2]) for i in iss):
        continue
    if covered.get(r['id']) == r['step_key'] or r['id'][:40] in done40:
        continue
    other = [i for i in iss if not i.startswith(READ_TAGS)]
    tg.append({'id': r['id'], 'step_key': r['step_key'], 'step_bytes': r.get('step_bytes') or 0, 'reused': r.get('reused'),
               'src_parts_keys': detail_src(r), 'issues': iss, 'class1_candidate': not other and not r.get('standins') and not r.get('needs')})
tg.sort(key=lambda x: (not x['class1_candidate'], x['step_bytes']))
mine = [x for i, x in enumerate(tg) if i % n == k - 1]
tasks = []; WIN = 3; prev = []
for j, x in enumerate(mine):
    tag = f'Q{tg.index(x):03d}_{x["id"][:8]}'
    jid = f'f-ifc-{x["id"][:40]}-readback'
    o = f'out/{tag}/s_x24'
    fetch = (f'mkdir -p in ref out/{tag} && aws s3 cp --only-show-errors s3://{B}/{x["step_key"]} in/{tag}.step && '
             f'aws s3api head-object --bucket {B} --key {x["step_key"]} > ref/{tag}.head.json && '
             '(' + ' || '.join(f'aws s3 cp --only-show-errors s3://{B}/{sk} ref/{tag}.src_parts.jsonl.gz' for sk in x['src_parts_keys']) + ' || true)')
    after = [f's_{prev[j - WIN]}_x24'] if j >= WIN else []
    tasks.append({'name': f'fetch_{tag}', 'cmd': fetch, 'threads': 1, 'mem_gb': 1, 'deps': [], 'after': after, 'outputs': [f'ref/{tag}.head.json']})
    prev.append(tag)
    tasks.append({'name': f's_{tag}_x24', 'cmd': f'nice -n 19 {PY} pkg/step_verify_big.py in/{tag}.step {o}.json --parts {o}.parts.jsonl.gz '
                                                 f'--chunk-mb 24 --workers {a.workers} --mem-gb 16 --max-check 0 --workdir wd/{tag} > {o}.log 2>&1',
                  'threads': a.workers + 1, 'mem_gb': 16, 'deps': [f'fetch_{tag}'], 'outputs': [f'{o}.json', f'{o}.log']})
    fr = f'out/{tag}/final_readback_x24.json'
    src = f'$( [ -s ref/{tag}.src_parts.jsonl.gz ] && echo --src-parts ref/{tag}.src_parts.jsonl.gz )'
    tasks.append({'name': f'final_{tag}_x24', 'cmd': f'{PY} pkg/to_final_result.py {o}.json {o}.parts.jsonl.gz --pipeline ifc --model-id {x["id"]} '
                                                     f'--step-key {x["step_key"]} {src} --grade-join pkg/grade_join.py -o {fr} > {fr}.log 2>&1 && '
                                                     f'aws s3 cp --only-show-errors {fr} {OUT}/results/{jid}.json && '
                                                     f'aws s3 cp --only-show-errors {o}.parts.jsonl.gz {OUT}/detail/{jid}.step_parts.jsonl.gz',
                  'threads': 1, 'mem_gb': 1, 'deps': [f's_{tag}_x24'], 'outputs': [fr, fr + '.log']})
    tasks.append({'name': f'clean_{tag}', 'cmd': f'rm -rf in/{tag}.step wd/{tag}', 'threads': 1, 'mem_gb': 0, 'deps': [], 'after': [f's_{tag}_x24']})
suffix = '' if n == 1 else f'_{k}_of_{n}'
json.dump(tasks, open(os.path.join(H, f'tasks_p4{suffix}.json'), 'w'), indent=1)
json.dump(tg, open(os.path.join(H, 'p4_targets.json'), 'w'), indent=1)
c1 = [x for x in mine if x['class1_candidate']]
print(len(mine), 'models', round(sum(x['step_bytes'] for x in mine) / 2**30, 1), 'GB;', len(c1), 'class-1 candidates',
      round(sum(x['step_bytes'] for x in c1) / 2**30, 1), 'GB; below 1 GB:', sum(1 for x in mine if x['step_bytes'] < 1 << 30), '->', f'tasks_p4{suffix}.json')
