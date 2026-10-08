#!/bin/bash
# READ-ONLY partial-tier PDF measurement: a seeded random sample of 300 shipped PDFs per disk (from the p1 stats reservoir), per file pages,
# sheet size, vector paths, text length, raster cover, and a rule label (checked against 600 hand-labelled PDFs: 97.3% drawing-vs-not);
# plus candidate drawing sheets (>= 17 in, vector) from distinct projects -> contact sheets. Output /opt/report/assets/ppdf/.
export AWS_DEFAULT_REGION=ap-south-1
D=/opt/report; O=$D/assets/ppdf; mkdir -p $O $D/work/ppdf
if systemctl is-active -q z3repppdf; then echo running; tail -n 3 $O/log.txt; exit 0; fi
if [ -f $O/finished ]; then echo "finished $(cat $O/finished)"; tail -n 4 $O/log.txt; exit 0; fi
cat > $D/rep_ppdf.py <<'PYEOF'
import os, json, random, time
import boto3, fitz
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt; import matplotlib.image as mpimg
from concurrent.futures import ThreadPoolExecutor
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; PK = 'cad-disk-extract/dataset/packages/3d_partial/'
O = '/opt/report/assets/ppdf'; W = '/opt/report/work/ppdf'
S = json.load(open('/opt/report/out/samples_p1.json'))
def label(x):
    w, h = x.get('w_in') or 0, x.get('h_in') or 0; big = max(w, h); small = min(w, h)
    v = x.get('vector_paths') or 0; r = x.get('raster_cover') or 0; t = x.get('text_chars') or 0
    letter = big <= 11.7 and small <= 8.6
    if r >= 0.5 and v < 200: return 'drawing_raster' if not letter else 'not_drawing'
    if letter and (v < 40 or (t > 800 and v < 160)): return 'not_drawing'
    return 'drawing_vector'
def one(arg):
    i, disk, pid, sha, nb, rp = arg
    rec = {'i': i, 'disk': disk, 'sha256': sha, 'project_id': pid, 'relpath': rp, 'bytes': nb}
    try:
        b = s3.get_object(Bucket=B, Key=f'{PK}{pid}/{rp}')['Body'].read()
        doc = fitz.open(stream=b, filetype='pdf'); rec['pages'] = doc.page_count
        p = doc[0]; r = p.rect; rec['w_in'] = round(r.width / 72, 2); rec['h_in'] = round(r.height / 72, 2)
        rec['text_chars'] = len(p.get_text().strip())
        try: rec['vector_paths'] = len(p.get_drawings())
        except Exception: rec['vector_paths'] = None
        area = r.width * r.height; cov = 0.0
        for im in p.get_image_info():
            bb = fitz.Rect(im['bbox']) & r; cov += bb.width * bb.height
        rec['raster_cover'] = round(min(1.0, cov / area), 3) if area else None
        rec['label'] = label(rec)
        if rec['label'] == 'drawing_vector' and max(rec['w_in'], rec['h_in']) >= 17:
            z = 600 / max(r.width, r.height); p.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False).save(f'{W}/t{i}.png'); rec['thumb'] = True
    except Exception as e:
        rec['error'] = f'{type(e).__name__}: {str(e)[:120]}'
    return rec
jobs = []
for disk in ('data-3', 'data-4'):
    rows = S.get(f'{disk}|drawings/pdf') or []
    byk = {}
    for pid, sha, b, rp in rows: byk.setdefault(sha, (pid, b, rp))
    shas = sorted(byk); random.Random(20261006).shuffle(shas)
    for sha in shas[:300]:
        pid, b, rp = byk[sha]; jobs.append((len(jobs), disk, pid, sha, b, rp))
with ThreadPoolExecutor(24) as tp: out = list(tp.map(one, jobs))
json.dump(out, open(f'{O}/pdf_sample.json', 'w'), indent=1)
# range candidates: one vector sheet >= 17 in per project, both disks
cand = []; seen = set()
for r in out:
    if r.get('thumb') and r['project_id'] not in seen:
        cand.append(r); seen.add(r['project_id'])
cand = cand[:48]; json.dump(cand, open(f'{O}/range_cands.json', 'w'), indent=1)
for sh in range(0, len(cand), 24):
    fig, axs = plt.subplots(4, 6, figsize=(36, 22))
    for k, ax in enumerate(axs.flat):
        ax.axis('off'); j = sh + k
        if j >= len(cand): continue
        ax.imshow(mpimg.imread(f"{W}/t{cand[j]['i']}.png")); ax.set_title(f"c{j} {cand[j]['disk']} {cand[j]['w_in']}x{cand[j]['h_in']} {cand[j]['relpath'].rsplit('/', 1)[-1][:34]}", fontsize=13)
    plt.tight_layout(); plt.savefig(f'{O}/cands_{sh // 24}.jpg', dpi=50); plt.close()
print('DONE', len(out), 'labels', {d: {l: sum(1 for r in out if r['disk'] == d and r.get('label') == l) for l in ('drawing_vector', 'drawing_raster', 'not_drawing')} for d in ('data-3', 'data-4')},
      'errors', sum(1 for r in out if r.get('error')), 'range candidates', len(cand), flush=True)
PYEOF
date -u +%FT%TZ > $O/started
systemctl reset-failed z3repppdf 2>/dev/null
systemd-run --unit=z3repppdf --collect --working-directory=$D --setenv=AWS_DEFAULT_REGION=ap-south-1 /bin/bash -c \
  "/opt/report/venv/bin/python $D/rep_ppdf.py > $O/log.txt 2>&1; echo rc=\$? >> $O/log.txt; date -u +%FT%TZ > $O/finished"
sleep 20; echo "started: $(systemctl is-active z3repppdf)"; tail -n 3 $O/log.txt
