#!/bin/bash
# READ-ONLY: "one job, three ways" search in chosen packages: marks that have a shop drawing PDF + an NC1 program AND appear in a shipped
# IFC model of the same package (quoted string match), with the IFC entity lines that carry them. Output /opt/report/assets/join/three_ways.json
export AWS_DEFAULT_REGION=ap-south-1
/opt/report/venv/bin/python - <<'PY'
import json, re, collections, boto3
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; PK = 'cad-disk-extract/dataset/packages/3d/'
P = {p['id']: p for p in json.load(open('/opt/report/out/projects_t2.json'))}
want = [k for k in P if any(s in k for s in ('MT20_023 (Issaquah', 'MT15_045', 'MT12_024'))]
def stem(rp):
    b = rp.rsplit('/', 1)[-1].rsplit('.', 1)[0]; return re.sub(r'-[0-9a-f]{6}$', '', b)
res = []
for pid in want:
    man = s3.get_object(Bucket=B, Key=f'{PK}{pid}/manifest.jsonl')['Body'].read().decode('utf-8', 'surrogateescape')
    pdf, nc1, ifc, stp = {}, {}, [], []
    for l in man.split('\n'):
        if not l.strip(): continue
        r = json.loads(l); rp = r['relpath']
        if rp.startswith('drawings/pdf/'): pdf.setdefault(stem(rp).lower(), rp)
        elif rp.startswith('fab/nc1/'): nc1.setdefault(stem(rp).lower(), rp)
        elif rp.startswith('model/ifc/') and rp.lower().endswith('.ifc'): ifc.append((rp, r['bytes']))
        elif rp.startswith('model/step/'): stp.append((rp, r['bytes'], r.get('converted_from'), r.get('model_id')))
    both = set(pdf) & set(nc1)
    print('RESULT', pid[18:90], 'pdf', len(pdf), 'nc1', len(nc1), 'pdf&nc1', len(both), 'ifc', len(ifc), 'step', len(stp), flush=True)
    for rp, nb in sorted(ifc, key=lambda x: x[1])[:40]:
        if nb > 60e6: continue
        txt = s3.get_object(Bucket=B, Key=f'{PK}{pid}/{rp}')['Body'].read().decode('latin1')
        hits = {}
        for m in both:
            k = txt.lower().count("'" + m + "'")
            if k: hits[m] = k
        if not hits: continue
        top = sorted(hits.items(), key=lambda x: -x[1])[:8]
        lines = {}
        for m, k in top[:3]:
            lines[m] = [ln[:220] for ln in txt.split('\n') if ("'" + m + "'") in ln.lower()][:4]
        st = [s for s in stp if s[2] == rp]
        res.append({'project_id': pid, 'ifc': rp, 'ifc_bytes': nb, 'marks_in_ifc': len(hits), 'top': top, 'lines': lines,
                    'step_from_this_ifc': st[:1], 'pdf': {m: pdf[m] for m, _ in top}, 'nc1': {m: nc1[m] for m, _ in top}})
        print('RESULT  ifc', rp[:70], nb, 'marks', len(hits), top[:4], 'step', bool(st), flush=True)
json.dump(res, open('/opt/report/assets/join/three_ways.json', 'w'), indent=1)
PY
