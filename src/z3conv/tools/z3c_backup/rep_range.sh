#!/bin/bash
# READ-ONLY: render page 1 of each picked shop/erection drawing (range_pick.json) to JPEG: 1800 px (page view) and 2800 px (full size).
# Output /opt/report/assets/range/. Synchronous (a few minutes).
export AWS_DEFAULT_REGION=ap-south-1
mkdir -p /opt/report/assets/range
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/coord_tmp/range_pick.json /opt/report/work/range_pick.json
/opt/report/venv/bin/python - <<'PY'
import json, boto3, fitz
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; PK = 'cad-disk-extract/dataset/packages/3d/'
pick = json.load(open('/opt/report/work/range_pick.json')); meta = []
for n, (disk, i, pid, rp, w, h) in enumerate(pick, 1):
    b = s3.get_object(Bucket=B, Key=f'{PK}{pid}/{rp}')['Body'].read()
    d = fitz.open(stream=b, filetype='pdf'); p = d[0]; r = p.rect
    for width, tag in ((1800, ''), (2800, '_full')):
        z = width / max(r.width, r.height); pix = p.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
        pix.save(f'/opt/report/assets/range/r{n:02d}{tag}.jpg', jpg_quality=88)
    meta.append({'n': n, 'disk': disk, 'sample_i': i, 'project_id': pid, 'relpath': rp, 'w_in': w, 'h_in': h, 'pages': d.page_count, 'bytes': len(b)})
    print('RESULT', n, disk, pid[18:70], rp[:50], flush=True)
json.dump(meta, open('/opt/report/assets/range/range.json', 'w'), indent=1)
PY
