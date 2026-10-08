#!/bin/bash
# READ-ONLY: assets for the report's "join" example (one plate mark three ways): the shop-drawing sheet (PDF page 1 -> JPEG),
# the DXF outline (ezdxf drawing add-on -> PNG) and the NC1 program text. Output /opt/report/assets/pjoin/<mark>_*.
export AWS_DEFAULT_REGION=ap-south-1
mkdir -p /opt/report/work/pjoin
MARKS=${MARKS:-3m204,9787a,p65,m261,agp,p5007}
/opt/report/venv/bin/python - "$MARKS" <<'PY'
import sys, json, boto3, fitz, ezdxf, io
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; PK = 'cad-disk-extract/dataset/packages/3d_partial/'
C = json.load(open('/opt/report/assets/pjoin/candidates.json'))
OK = {(x['project_id'], x['mark_stem']) for x in json.load(open('/opt/report/assets/pjoin/screen.json')) if x['checks']['mark'] and x['checks']['profile'] and x['checks']['grade'] and x['checks']['qty_ok']}
want = sys.argv[1].split(',')
out = {}
for r in C:
    st = r['mark_stem']
    if st not in want or st in out or (r['project_id'], st) not in OK: continue
    pid = r['project_id']; tag = st
    pb = s3.get_object(Bucket=B, Key=f"{PK}{pid}/{r['pdf']}")['Body'].read()
    d = fitz.open(stream=pb, filetype='pdf'); p = d[0]; z = 1300 / max(p.rect.width, p.rect.height)
    p.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False).save(f'/opt/report/assets/pjoin/{tag}_sheet.jpg', jpg_quality=90)
    words = p.get_text()
    db = s3.get_object(Bucket=B, Key=f"{PK}{pid}/{r['dxf']}")['Body'].read()
    open('/opt/report/work/pjoin/j.dxf', 'wb').write(db); doc = ezdxf.readfile('/opt/report/work/pjoin/j.dxf')
    fig = plt.figure(figsize=(10.4, 7.6), dpi=100); ax = fig.add_axes([0, 0, 1, 1]); ax.set_facecolor('white')
    Frontend(RenderContext(doc), MatplotlibBackend(ax)).draw_layout(doc.modelspace(), finalize=True)
    fig.savefig(f'/opt/report/assets/pjoin/{tag}_dxf.png', dpi=100, facecolor='white'); plt.close(fig)
    nt = s3.get_object(Bucket=B, Key=f"{PK}{pid}/{r['nc1']}")['Body'].read().decode('latin1')
    ents = sorted({e.dxftype() for e in doc.modelspace()})
    out[st] = {'project_id': pid, 'pdf': r['pdf'], 'dxf': r['dxf'], 'nc1': r['nc1'], 'nc1_header': r['nc1_header'], 'nc1_text_head': nt.replace('\r', '').split('\n')[:40],
               'dxf_ext': r['dxf_ext'], 'dxf_entities': ents, 'pdf_text_excerpt': words[:1500], 'pdf_page_in': r.get('pdf_page_in')}
    print('RESULT', st, pid[18:80], r['nc1_header'].get('profile'), r['dxf_ext'], flush=True)
json.dump(out, open('/opt/report/assets/pjoin/join_examples2.json', 'w'), indent=1)
PY
