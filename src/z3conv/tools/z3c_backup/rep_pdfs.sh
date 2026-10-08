#!/bin/bash
# READ-ONLY PDF channel measurement for the report: a random sample of shipped PDF files (seeded), per file: pages, first-page size,
# vector path count, text length, raster coverage; first-page thumbnails -> contact sheets (for a human drawing / not-drawing label).
# Output /opt/report/assets/pdf/. Idempotent: first call starts unit z3reppdf.
export AWS_DEFAULT_REGION=ap-south-1
D=/opt/report; O=$D/assets/pdf; mkdir -p $O $D/work/pdf
if systemctl is-active -q z3reppdf; then echo running; tail -n 3 $O/log.txt; exit 0; fi
if [ -f $O/finished ]; then echo "finished $(cat $O/finished)"; tail -n 6 $O/log.txt; exit 0; fi
cat > $D/rep_pdfs.py <<'PYEOF'
import os, json, random, collections, time, io
import boto3, fitz
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; PK = 'cad-disk-extract/dataset/packages/3d/'
O = '/opt/report/assets/pdf'; W = '/opt/report/work/pdf'
N = int(os.environ.get('PDF_N', '300'))
S = json.load(open('/opt/report/out/samples_t1.json'))['drawings/pdf']
rnd = random.Random(424242)
byk = {}
for pid, sha, b in S: byk.setdefault(sha, (pid, b))
shas = sorted(byk); rnd.shuffle(shas); shas = shas[:N]
need = collections.defaultdict(set)
for sha in shas: need[byk[sha][0]].add(sha)
rel = {}
for pid, ss in need.items():
    man = s3.get_object(Bucket=B, Key=f'{PK}{pid}/manifest.jsonl')['Body'].read().decode('utf-8', 'surrogateescape')
    for l in man.split('\n'):
        if '"sha256": "' in l:
            r = json.loads(l)
            if r.get('sha256') in ss and r['relpath'].startswith('drawings/pdf/') and r['sha256'] not in rel:
                rel[r['sha256']] = (pid, r['relpath'], r['bytes'], r.get('role'))
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
systemctl reset-failed z3reppdf 2>/dev/null
systemd-run --unit=z3reppdf --collect --working-directory=$D --setenv=AWS_DEFAULT_REGION=ap-south-1 /bin/bash -c \
  "/opt/report/venv/bin/python $D/rep_pdfs.py > $O/log.txt 2>&1; echo rc=\$? >> $O/log.txt; date -u +%FT%TZ > $O/finished"
sleep 20; echo "started: $(systemctl is-active z3reppdf)"; tail -n 3 $O/log.txt
