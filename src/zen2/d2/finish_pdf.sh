#!/bin/bash
# after the main run: redo annotated PDFs with annotation flattening (ANNOT_ layers), re-sync, then build the index
cd /work/2d
L=logs/finish_pdf.log
echo "$(date -u +%FT%TZ) waiting for main run" >> $L
while pgrep -f run_pdf_all.sh > /dev/null; do sleep 20; done
echo "$(date -u +%FT%TZ) main run finished; redo annotated" >> $L
./venv/bin/python run_pdf.py 20 --only "$(cat state/annotated_pdfs.txt)" --redo >> $L 2>&1
echo "$(date -u +%FT%TZ) redo exit $?" >> $L
./sync_pdf.sh >> $L 2>&1
./venv/bin/python - >> $L 2>&1 <<'P'
import json, sys; sys.path.insert(0, '/work/2d'); import status
s = json.load(open('/work/2d/state/status_pdf.json')); s['stage'] = 'done (synced to dxf_from_pdf/; annotated PDFs re-run with ANNOT_ layers)'; status.put_part('pdf', s)
P
echo "$(date -u +%FT%TZ) FINISH DONE" >> $L
