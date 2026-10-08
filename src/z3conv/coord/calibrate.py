#!/usr/bin/env python3
"""Classifier calibration sample: ~N models per (pipeline, class), stratified over reuse source / version / top issue, renders laid out
as labelled contact sheets -> _state/conv/calibration/<pipe>_class<k>.png + classifier_calibration.json (sample + per-model signals).
usage: calibrate.py [N=20] [--tag NAME]"""
import sys, os, json, gzip, random, io, collections, time
import boto3
from botocore.config import Config
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

B = 'bim-proprietary-data'; ST = 'cad-disk-extract/zenitude-data-3/_state/conv'
s3 = boto3.client('s3', region_name='ap-south-1', config=Config(retries={'max_attempts': 20, 'mode': 'standard'}, max_pool_connections=64))
N = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 20
TAG = sys.argv[sys.argv.index('--tag') + 1] if '--tag' in sys.argv else time.strftime('%Y%m%dT%H%M')
rows = [json.loads(l) for l in gzip.decompress(s3.get_object(Bucket=B, Key=f'{ST}/index.jsonl.gz')['Body'].read()).decode().splitlines() if l.strip()]
rng = random.Random(11)
sample = []
for pipe in ('ifc', 'db1', 'sds2'):
    for k in (1, 2, 3):
        cand = [r for r in rows if r['pipeline'] == pipe and r['class'] == k]
        strata = collections.defaultdict(list)
        for r in cand:
            key = (r.get('reused'), (r['reasons'] + r['issues'] + [s['type'] for s in r['standins']] + ['-'])[0].split(':')[0])
            strata[key].append(r)
        pick = []
        keys = sorted(strata, key=lambda x: -len(strata[x]))
        while len(pick) < min(N, len(cand)):
            for kk in keys:
                if strata[kk] and len(pick) < N:
                    pick.append(strata[kk].pop(rng.randrange(len(strata[kk]))))
        sample += pick


def img(key):
    if not key:
        return None
    try:
        return mpimg.imread(io.BytesIO(s3.get_object(Bucket=B, Key=key)['Body'].read()), format='png')
    except Exception:
        return None


out = []
for pipe in ('ifc', 'db1', 'sds2'):
    for k in (1, 2, 3):
        grp = [r for r in sample if r['pipeline'] == pipe and r['class'] == k]
        if not grp:
            continue
        cols = 5; rws = (len(grp) + cols - 1) // cols
        fig = plt.figure(figsize=(cols * 4, rws * 3.4), dpi=80)
        for i, r in enumerate(grp):
            ax = fig.add_subplot(rws, cols, i + 1); ax.axis('off')
            im = img(r.get('render_key'))
            if im is not None:
                ax.imshow(im)
            else:
                ax.text(0.5, 0.5, 'no render', ha='center', va='center')
            lab = [f"#{i + 1} {r['id'][:10]} {'reused ' + str(r.get('reuse_from')) if r.get('reused') else 'new'} c{r['class']}{r.get('corpus') or ''}",
                   f"cov m={r.get('coverage_members')} c={r.get('coverage_connections')} inv={r.get('invalid_solids')}",
                   '; '.join((r['reasons'] + r['issues'])[:2])[:70], ', '.join(f"{s['type']}:{s['count']}" for s in r['standins'][:2])[:70]]
            ax.set_title('\n'.join(lab), fontsize=6.5, loc='left')
        fig.tight_layout()
        buf = io.BytesIO(); fig.savefig(buf, format='png'); plt.close(fig)
        key = f'{ST}/calibration/{TAG}/{pipe}_class{k}.png'
        s3.put_object(Bucket=B, Key=key, Body=buf.getvalue(), ContentType='image/png')
        out.append({'pipeline': pipe, 'class': k, 'sheet': key, 'models': [{'n': i + 1, 'id': r['id'], 'reused': r.get('reused'), 'reuse_from': r.get('reuse_from'),
                    'corpus': r.get('corpus'), 'render_key': r.get('render_key'), 'step_key': r.get('step_key'), 'reasons': r['reasons'], 'issues': r['issues'],
                    'standins': r['standins'][:5], 'coverage_members': r.get('coverage_members'), 'coverage_connections': r.get('coverage_connections'),
                    'invalid_solids': r.get('invalid_solids'), 'weight_ratio': r.get('weight_ratio')} for i, r in enumerate(grp)]})
doc = {'tag': TAG, 'created': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'per_class_target': N, 'sheets': out, 'outcome': None}
s3.put_object(Bucket=B, Key=f'{ST}/calibration/{TAG}/sample.json', Body=json.dumps(doc, indent=1, default=str).encode(), ContentType='application/json')
print(TAG, [(o['pipeline'], o['class'], len(o['models'])) for o in out])
