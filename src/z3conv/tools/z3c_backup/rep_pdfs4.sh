#!/bin/bash
# (data-4 stratum) READ-ONLY PDF channel measurement for the report: a random sample of shipped PDF files (seeded), per file: pages, first-page size,
# vector path count, text length, raster coverage; first-page thumbnails -> contact sheets (for a human drawing / not-drawing label).
# Output /opt/report/assets/pdf/. Idempotent: first call starts unit z3reppdf4.
export AWS_DEFAULT_REGION=ap-south-1
D=/opt/report; O=$D/assets/pdf4; mkdir -p $O $D/work/pdf4
if systemctl is-active -q z3reppdf4; then echo running; tail -n 3 $O/log.txt; exit 0; fi
if [ -f $O/finished ]; then echo "finished $(cat $O/finished)"; tail -n 6 $O/log.txt; exit 0; fi
cat > $D/rep_pdfs.py <<'PYEOF'
import os, json, random, collections, time, io
import boto3, fitz
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; PK = 'cad-disk-extract/dataset/packages/3d/'
O = '/opt/report/assets/pdf4'; W = '/opt/report/work/pdf4'
N = int(os.environ.get('PDF_N', '300'))
S = json.load(open('/opt/report/out/samples_t2.json'))['data-4|drawings/pdf']      # uniform reservoir sample of data-4 PDF rows
rnd = random.Random(424243)
byk = {}
for pid, sha, b, rp in S: byk.setdefault(sha, (pid, rp, b))
shas = sorted(byk); rnd.shuffle(shas); shas = shas[:N]
rel = {sha: (byk[sha][0], byk[sha][1], byk[sha][2], None) for sha in shas}
out = []
for i, sha in enumerate(shas):
    pid, rp, nb, role = rel.get(sha, (None, None, None, None))
    rec = {'i': i, 'sha256': sha, 'project_id': pid, 'relpath': rp, 'bytes': nb, 'role': role}
    try:
        loc = f'{W}/{i}.pdf'; s3.download_file(B, f'{PK}{pid}/{rp}', loc)
        doc = fitz.open(loc); rec['pages'] = doc.page_count
        p = doc[0]; r = p.rect; rec['w_in'] = round(r.width / 72, 2); rec['h_in'] = round(r.height / 72, 2)
        txt = p.get_text(); rec['text_chars'] = len(txt.strip())
        try: rec['vector_paths'] = len(p.get_drawings())
        except Exception: rec['vector_paths'] = None
        area = r.width * r.height; cov = 0.0
        for im in p.get_image_info():
            bb = fitz.Rect(im['bbox']) & r; cov += bb.width * bb.height
        rec['raster_cover'] = round(min(1.0, cov / area), 3) if area else None
        z = 360 / max(r.width, r.height); pix = p.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False); pix.save(f'{W}/t{i}.png')
        doc.close(); os.remove(loc)
    except Exception as e:
        rec['error'] = f'{type(e).__name__}: {str(e)[:120]}'
    out.append(rec)
    if (i + 1) % 25 == 0: print(i + 1, 'pdfs', flush=True)
json.dump(out, open(f'{O}/pdf_sample.json', 'w'), indent=1)
import matplotlib.image as mpimg
for sh in range(0, len(out), 30):
    fig, axs = plt.subplots(5, 6, figsize=(30, 25))
    for k, ax in enumerate(axs.flat):
        ax.axis('off'); j = sh + k
        if j >= len(out): continue
        f = f'{W}/t{j}.png'
        if os.path.exists(f): ax.imshow(mpimg.imread(f))
        rr = out[j]; ax.set_title(f"#{j} {rr.get('w_in')}x{rr.get('h_in')}in p{rr.get('pages')} v{rr.get('vector_paths')} r{rr.get('raster_cover')}", fontsize=13)
    plt.tight_layout(); plt.savefig(f'{O}/sheet_{sh // 30:02d}.png', dpi=55); plt.close()
print('DONE', len(out), flush=True)
PYEOF
date -u +%FT%TZ > $O/started
systemctl reset-failed z3reppdf4 2>/dev/null
systemd-run --unit=z3reppdf4 --collect --working-directory=$D --setenv=AWS_DEFAULT_REGION=ap-south-1 /bin/bash -c \
  "/opt/report/venv/bin/python $D/rep_pdfs.py > $O/log.txt 2>&1; echo rc=\$? >> $O/log.txt; date -u +%FT%TZ > $O/finished"
sleep 20; echo "started: $(systemctl is-active z3reppdf4)"; tail -n 3 $O/log.txt
