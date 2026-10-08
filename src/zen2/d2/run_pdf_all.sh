#!/bin/bash
# full PDF run: convert + validate all distinct PDFs, then link duplicates and sync to S3
cd /work/2d
./venv/bin/python run_pdf.py 24 >> logs/run_pdf.log 2>&1
echo "$(date -u +%FT%TZ) run_pdf exit $?" >> logs/run_pdf.log
./sync_pdf.sh >> logs/run_pdf.log 2>&1
./venv/bin/python - >> logs/run_pdf.log 2>&1 <<'P'
import json, sys; sys.path.insert(0, '/work/2d'); import status
s = json.load(open('/work/2d/state/status_pdf.json')); s['stage'] = 'done (synced to dxf_from_pdf/)'; status.put_part('pdf', s)
P
echo "$(date -u +%FT%TZ) ALL DONE" >> logs/run_pdf.log
