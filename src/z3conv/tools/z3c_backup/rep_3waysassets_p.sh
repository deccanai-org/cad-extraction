#!/bin/bash
# READ-ONLY: assets for the partial report's "one job, three ways": Skyline B12 (GEM Buildings), assembly B1045.
export AWS_DEFAULT_REGION=ap-south-1
/opt/report/venv/bin/python - <<'PY'
import json, re, boto3, fitz
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; PK = 'cad-disk-extract/dataset/packages/3d_partial/'
C = json.load(open('/opt/report/assets/pthree/candidates.json'))
r = next(c for c in C if c['assembly'] == 'B1045' and 'Skyline' in c['project_id'])
pid = r['project_id']
pb = s3.get_object(Bucket=B, Key=f"{PK}{pid}/{r['pdf'][0]}")['Body'].read(); d = fitz.open(stream=pb, filetype='pdf'); p = d[0]
for wpx, tag in ((1800, ''), (2800, '_full')):
    z = wpx / max(p.rect.width, p.rect.height); p.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False).save(f'/opt/report/assets/pthree/sheet{tag}.jpg', jpg_quality=90)
man = [json.loads(l) for l in s3.get_object(Bucket=B, Key=f'{PK}{pid}/manifest.jsonl')['Body'].read().decode('utf-8', 'surrogateescape').split('\n') if l.strip()]
st = next(x for x in man if x['relpath'] == r['step'])
out = {'project_id': pid, 'cand': r, 'pdf': {'relpath': r['pdf'][0], 'pages': d.page_count, 'size_in': [round(p.rect.width / 72, 1), round(p.rect.height / 72, 1)], 'text': p.get_text()[:5000]},
       'step_row': {k: st.get(k) for k in ('relpath', 'bytes', 'class', 'partial', 'converted_from', 'converter', 'model_id')}, 'nc1': {}}
for mk in [r['assembly'].lower()] + r['parts_with_nc1'][:3]:
    rp = next((x['relpath'] for x in man if x['relpath'].lower().startswith('fab/nc1/' + mk + '.') or re.match(r'fab/nc1/' + re.escape(mk) + r'-[0-9a-f]{6}\.nc1$', x['relpath'].lower())), None)
    if not rp: continue
    t = s3.get_object(Bucket=B, Key=f'{PK}{pid}/{rp}')['Body'].read().decode('latin1').replace('\r', '').split('\n')
    out['nc1'][mk] = {'relpath': rp, 'lines': t[:40]}
json.dump(out, open('/opt/report/assets/pthree/three_src.json', 'w'), indent=1)
print('RESULT', pid[18:90], r['pdf'][0], out['pdf']['size_in'], 'nc1', list(out['nc1']), 'step kind', (st.get('partial') or {}).get('kind'))
PY
