#!/bin/bash
# READ-ONLY: screen dimension-consistent join candidates for full agreement (mark, profile, grade, quantity) between the shop-drawing
# text, the NC1 header and the DXF extents. Output /opt/report/assets/pjoin/screen.json
export AWS_DEFAULT_REGION=ap-south-1
/opt/report/venv/bin/python - <<'PY'
import json, re, boto3, fitz
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; PK = 'cad-disk-extract/dataset/packages/3d_partial/'
C = json.load(open('/opt/report/assets/pjoin/candidates.json'))
def norm(s): return re.sub(r'\s+', '', (s or '')).lower()
res = []
for r in C:
    h = r.get('nc1_header') or {}; e = r.get('dxf_ext')
    if h.get('code') != 'B' or not e: continue
    try: L = float(h['length']); H = float(h['height'])
    except Exception: continue
    a, b = sorted(e, reverse=True); unit = None
    for f, u in ((25.4, 'in'), (1.0, 'mm')):
        if abs(a * f - L) < 0.6 and abs(b * f - H) < 0.6: unit = u
    if not unit: continue
    pb = s3.get_object(Bucket=B, Key=f"{PK}{r['project_id']}/{r['pdf']}")['Body'].read()
    d = fitz.open(stream=pb, filetype='pdf'); tx = d[0].get_text()
    T = norm(tx); mk = norm(h.get('mark')); prof = norm(h.get('profile')); gr = norm(h.get('grade')); q = h.get('qty', '').strip()
    has = {'mark': mk in T, 'profile': prof in T, 'grade': gr in T}
    # quantity as printed next to the profile ("14 PL1/2X..."), or a QTY field
    qm = re.findall(r'(?:^|\n)\s*(\d+)\s*(?:-\s*)?' + re.escape(h.get('profile', '').split('X')[0].strip()), tx, re.I)
    has['qty_near_profile'] = qm[:3]
    has['qty_ok'] = (q in qm) if qm else None
    res.append({**{k: r[k] for k in ('project_id', 'pdf', 'dxf', 'nc1', 'mark_stem')}, 'nc1': r['nc1'], 'header': h, 'dxf_ext': e, 'unit': unit, 'checks': has,
                'job_line': h.get('order'), 'pdf_head': tx[:400]})
ok = [x for x in res if x['checks']['mark'] and x['checks']['profile'] and x['checks']['grade'] and x['checks']['qty_ok']]
json.dump(res, open('/opt/report/assets/pjoin/screen.json', 'w'), indent=1)
print('RESULT screened', len(res), 'all-agree', len(ok))
for x in ok[:20]:
    h = x['header']; print('RESULT', x['mark_stem'], h['grade'], h['qty'], h['profile'], h['length'], h['height'], x['dxf_ext'], x['unit'], x['project_id'][18:85], '| job', h.get('order'))
PY
