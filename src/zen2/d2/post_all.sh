#!/bin/bash
# after finish_pdf.sh: chunked validation of timed-out heavy pages, refresh pdf status, upload results, final artefacts
cd /work/2d; L=logs/post_all.log
while pgrep -f finish_pdf.sh > /dev/null; do sleep 20; done
while pgrep -f run_sha_dxf.py > /dev/null; do sleep 20; done
echo "$(date -u +%FT%TZ) start heavy validation" >> $L
./venv/bin/python validate_heavy.py 16 >> $L 2>&1
./venv/bin/python - >> $L 2>&1 <<'P'
import json, sys; sys.path.insert(0, '/work/2d'); import status, run_pdf
recs = {}
for l in open('/work/2d/state/pdf_results.jsonl'):
    r = json.loads(l); recs[r['sha256']] = r
with open('/work/2d/state/pdf_results.final.jsonl', 'w') as f:
    for r in recs.values():
        f.write(json.dumps(r, default=str) + '\n')
s = run_pdf.summarize(list(recs.values()), len(run_pdf.load_jobs()), 0)
s['stage'] = 'done (synced to dxf_from_pdf/; annotated PDFs re-run with ANNOT_ layers; heavy page validated in chunks)'
status.put_part('pdf', s)
print('pdf status refreshed', s['pages_done'], s['iou_tol1px'])
P
cp state/pdf_results.final.jsonl state/pdf_results.jsonl
aws s3 cp --only-show-errors state/pdf_results.jsonl s3://annotationprod/cad-disk-extract/zenitude-data-2/_state/d2_pdf_results.jsonl
[ -d out/qa ] && aws s3 sync --only-show-errors out/qa/ s3://annotationprod/cad-disk-extract/zenitude-data-2/_state/d2_qa/flagged/
./final_upload.sh
echo "$(date -u +%FT%TZ) POST ALL DONE" >> $L
