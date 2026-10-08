#!/bin/bash
# final artefacts: sha findings -> status; dxf_from_sha; json/drawings; drawing_index.json
B=s3://annotationprod/cad-disk-extract/zenitude-data-2
cd /work/2d; L=logs/final_upload.log
echo "$(date -u +%FT%TZ) start" >> $L
./venv/bin/python sha_findings.py >> $L 2>&1
./venv/bin/python pdf_fidelity.py >> $L 2>&1
aws s3 sync --only-show-errors /work/2d/out/dxf_from_sha/ $B/dxf_from_sha/ >> $L 2>&1; echo "$(date -u +%FT%TZ) dxf_from_sha synced rc=$?" >> $L
aws s3 cp --only-show-errors /work/2d/state/sha_dxf_results.jsonl $B/_state/d2_sha_dxf_results.jsonl >> $L 2>&1
rm -rf /work/2d/out/json/drawings; ./venv/bin/python pdf_json.py 12 >> $L 2>&1
aws s3 sync --only-show-errors /work/2d/out/json/drawings/ $B/json/drawings/ >> $L 2>&1; echo "$(date -u +%FT%TZ) json/drawings synced rc=$?" >> $L
./venv/bin/python build_index.py > state/index_summary.json 2>> $L
aws s3 cp --only-show-errors /work/2d/out/json/drawing_index.json $B/json/drawing_index.json >> $L 2>&1; echo "$(date -u +%FT%TZ) index uploaded rc=$?" >> $L
./venv/bin/python - >> $L 2>&1 <<'P'
import json, sys; sys.path.insert(0, '/work/2d'); import status
s = json.load(open('/work/2d/state/index_summary.json'))
status.put_part('index', {'stage': 'done', 'output': 's3://annotationprod/cad-disk-extract/zenitude-data-2/json/drawing_index.json', **s})
P
echo "$(date -u +%FT%TZ) FINAL DONE" >> $L
