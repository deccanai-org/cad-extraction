#!/bin/bash
# READ-ONLY: assets for "one job, three ways" (Issaquah MT20_023, sequence 52, assembly B52006): assembly drawing -> JPEG (1800 px + 2800 px),
# NC1 texts of B52006 and p14420, the class-1 STEP of the sequence model -> GLB + still (same renderer as the model tiles).
export AWS_DEFAULT_REGION=ap-south-1
mkdir -p /opt/report/assets/three
/opt/report/venv/bin/python - <<'PY'
import json, re, boto3, fitz, sys
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; PK = 'cad-disk-extract/dataset/packages/3d/'
T = json.load(open('/opt/report/assets/join/three_ways3.json'))
r = next(x for x in T if x['assembly'] == 'B52006')
pid = 'Zenitude-data-3__Completed_Projects_Data_0102_Lundahl LIC_MT20_023 (Issaquah Middle School).7z'
pb = s3.get_object(Bucket=B, Key=f"{PK}{pid}/{r['pdf'][0]}")['Body'].read(); d = fitz.open(stream=pb, filetype='pdf'); p = d[0]
for w, tag in ((1800, ''), (2800, '_full')):
    z = w / max(p.rect.width, p.rect.height); p.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False).save(f'/opt/report/assets/three/b52006{tag}.jpg', jpg_quality=90)
out = {'project_id': pid, 'assembly': r, 'nc1': {}}
for mk in ('b52006', 'p14420'):
    man_rp = r['nc1'][0] if mk == 'b52006' else None
    if mk == 'p14420':
        man = s3.get_object(Bucket=B, Key=f'{PK}{pid}/manifest.jsonl')['Body'].read().decode('utf-8', 'surrogateescape')
        man_rp = next(json.loads(l)['relpath'] for l in man.split('\n') if '"fab/nc1/p14420' in l)
    t = s3.get_object(Bucket=B, Key=f'{PK}{pid}/{man_rp}')['Body'].read().decode('latin1').replace('\r', '').split('\n')
    out['nc1'][mk] = {'relpath': man_rp, 'lines': t[:80], 'n_lines': len(t), 'blocks': sorted({x.strip() for x in t if re.match(r'^[A-Z]{2}$', x.strip())})}
out['pdf'] = {'relpath': r['pdf'][0], 'size_in': [round(p.rect.width / 72, 1), round(p.rect.height / 72, 1)], 'text': p.get_text()[:4000]}
json.dump(out, open('/opt/report/assets/three/three.json', 'w'), indent=1)
print('RESULT drawing', r['pdf'][0], out['pdf']['size_in'], 'nc1', [v['relpath'] for v in out['nc1'].values()])
PY
