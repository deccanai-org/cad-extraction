#!/bin/bash
# READ-ONLY: contact sheet of candidate class-1 models (grader renders) for the report's sample tiles. Output /opt/report/assets/cands_*.png
export AWS_DEFAULT_REGION=ap-south-1
/opt/report/venv/bin/python - <<'PY'
import json, gzip, random, io, boto3, collections
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt; import matplotlib.image as mpimg
s3 = boto3.client('s3'); B = 'bim-proprietary-data'
P = json.load(open('/opt/report/out/projects_t1.json'))
proj_ok = {p['id']: p for p in P if p['per_channel'].get('drawings/pdf', 0) > 50 and p['per_channel'].get('fab/nc1', 0) > 20}
idx = {}
for disk, st in (('data-3', 'cad-disk-extract/zenitude-data-3/_state/conv'), ('data-4', 'cad-disk-extract/zentitude-data-4/_state/conv2')):
    for l in gzip.decompress(s3.get_object(Bucket=B, Key=f'{st}/index.jsonl.gz')['Body'].read()).decode().split('\n'):
        if l.strip():
            r = json.loads(l)
            if r.get('class') == 1: idx[r['id']] = (disk, r)
c = []
for p in proj_ok.values():
    for s in p['steps']:
        e = idx.get(s['model_id'])
        if not e: continue
        r = e[1]
        if r.get('render_key') and 2e6 < (s['bytes'] or 0) < 6e7:
            c.append((p['disk'], s['step_source'], p['id'], s['relpath'], s['bytes'], r['render_key'], s['model_id'], r.get('parts_step')))
rnd = random.Random(5); rnd.shuffle(c)
pick = []; seenp = set(); per = collections.Counter()
for t in sorted(c, key=lambda t: (t[1] != 'ifc', rnd.random())):
    key = (t[0], t[1])
    if t[2] in seenp or per[key] >= {('data-3','ifc'): 14, ('data-4','ifc'): 14}.get(key, 6): continue
    pick.append(t); seenp.add(t[2]); per[key] += 1
    if len(pick) >= 48: break
json.dump(pick, open('/opt/report/assets/cands.json', 'w'), indent=1)
for sheet in range(0, len(pick), 24):
    fig, axs = plt.subplots(4, 6, figsize=(30, 17))
    for i, ax in enumerate(axs.flat):
        ax.axis('off')
        if sheet + i >= len(pick): continue
        t = pick[sheet + i]
        try:
            img = mpimg.imread(io.BytesIO(s3.get_object(Bucket=B, Key=t[5])['Body'].read()), format='png')
            ax.imshow(img[40:, :, :])
        except Exception as e:
            ax.text(0.5, 0.5, str(e)[:40])
        ax.set_title(f'{sheet + i}: {t[0]} {t[1]} {t[4] // 1000000}MB {t[7]}p\n{t[2].split("__", 1)[1][:60]}', fontsize=9)
    plt.tight_layout(); plt.savefig(f'/opt/report/assets/cands_{sheet // 24}.png', dpi=60); plt.close()
print('RESULT picked', len(pick), dict(per))
PY
