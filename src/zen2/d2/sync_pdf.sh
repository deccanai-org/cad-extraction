#!/bin/bash
# link duplicates, then upload dxf_from_pdf + results + flagged diffs (inside the project prefix only)
B=s3://annotationprod/cad-disk-extract/zenitude-data-2
cd /work/2d && ./venv/bin/python link_dups.py
aws s3 sync --only-show-errors /work/2d/out/dxf_from_pdf/ $B/dxf_from_pdf/
aws s3 cp --only-show-errors /work/2d/state/pdf_results.jsonl $B/_state/d2_pdf_results.jsonl
[ -d /work/2d/out/qa ] && aws s3 sync --only-show-errors /work/2d/out/qa/ $B/_state/d2_qa/flagged/
echo "sync done $(find /work/2d/out/dxf_from_pdf -name '*.dxf' | wc -l) dxf"
