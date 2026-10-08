#!/bin/bash
# READ-ONLY, fast: for given IFC models of one package, collect every quoted string once, intersect with marks that have both a shop
# drawing PDF and an NC1 program, and dump the IFC entity lines / NC1 headers / PDF text for the best marks.
# Output /opt/report/assets/join/three_ways2.json
export AWS_DEFAULT_REGION=ap-south-1
/opt/report/venv/bin/python - <<'PY'
import json, re, collections, boto3, fitz
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; PK = 'cad-disk-extract/dataset/packages/3d/'
pid = 'Zenitude-data-3__Completed_Projects_Data_0102_Lundahl LIC_MT20_023 (Issaquah Middle School).7z'
def stem(rp):
    b = rp.rsplit('/', 1)[-1].rsplit('.', 1)[0]; return re.sub(r'-[0-9a-f]{6}$', '', b)
man = s3.get_object(Bucket=B, Key=f'{PK}{pid}/manifest.jsonl')['Body'].read().decode('utf-8', 'surrogateescape')
pdf, nc1, ifc, stp = {}, {}, [], {}
for l in man.split('\n'):
    if not l.strip(): continue
    r = json.loads(l); rp = r['relpath']
    if rp.startswith('drawings/pdf/'): pdf.setdefault(stem(rp).lower(), rp)
    elif rp.startswith('fab/nc1/'): nc1.setdefault(stem(rp).lower(), rp)
    elif rp.startswith('model/ifc/') and rp.lower().endswith('.ifc'): ifc.append((rp, r['bytes']))
    elif rp.startswith('model/step/'): stp[r.get('converted_from')] = (rp, r['bytes'], r.get('model_id'))
both = set(pdf) & set(nc1)
out = []
for rp, nb in sorted(ifc, key=lambda x: x[1]):
    if nb > 3e6 or not 'IMS_Job' in rp: continue
    txt = s3.get_object(Bucket=B, Key=f'{PK}{pid}/{rp}')['Body'].read().decode('latin1')
    q = collections.Counter(s.lower() for s in re.findall(r"'([^'\n]{1,40})'", txt))
    hits = {m: q[m] for m in both if q.get(m)}
    ents = collections.Counter(re.findall(r'=\s*(IFC[A-Z]+)\(', txt))
    out.append({'ifc': rp, 'bytes': nb, 'step': stp.get(rp), 'hits': sorted(hits.items(), key=lambda x: -x[1])[:12], 'n_hits': len(hits),
                'entities': {k: ents[k] for k in ('IFCELEMENTASSEMBLY', 'IFCBEAM', 'IFCCOLUMN', 'IFCMEMBER', 'IFCPLATE', 'IFCSTAIR', 'IFCSTAIRFLIGHT', 'IFCRAILING', 'IFCMECHANICALFASTENER', 'IFCDISCRETEACCESSORY') if ents.get(k)}})
best = sorted([o for o in out if o['step']], key=lambda o: -o['n_hits'])[:6]
for o in best:
    txt = s3.get_object(Bucket=B, Key=f"{PK}{pid}/{o['ifc']}")['Body'].read().decode('latin1')
    o['mark_lines'] = {}
    for m, k in o['hits'][:4]:
        o['mark_lines'][m] = [ln[:260] for ln in txt.split('\n') if ("'" + m + "'") in ln.lower()][:6]
        nt = s3.get_object(Bucket=B, Key=f'{PK}{pid}/{nc1[m]}')['Body'].read().decode('latin1').replace('\r', '').split('\n')
        o.setdefault('nc1', {})[m] = {'relpath': nc1[m], 'head': nt[:22]}
        pb = s3.get_object(Bucket=B, Key=f'{PK}{pid}/{pdf[m]}')['Body'].read(); d = fitz.open(stream=pb, filetype='pdf')
        o.setdefault('pdf', {})[m] = {'relpath': pdf[m], 'pages': d.page_count, 'size_in': [round(d[0].rect.width / 72, 1), round(d[0].rect.height / 72, 1)], 'text': d[0].get_text()[:900]}
    print('RESULT', o['ifc'], o['bytes'], 'step', o['step'][0][:60], 'marks', o['n_hits'], o['hits'][:5], o['entities'], flush=True)
json.dump({'project_id': pid, 'models': out, 'best': best}, open('/opt/report/assets/join/three_ways2.json', 'w'), indent=1)
PY
