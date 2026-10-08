#!/bin/bash
# one coordinator round after the scan: rebuild the index / class lists / conv_status.json; final build on the operator's flag.
export AWS_DEFAULT_REGION=ap-south-1
PY=/opt/z3c/venv/bin/python; K=/opt/z3c/kit
ST=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/conv
CTL=s3://annotationprod/cad-disk-extract/_control/z3conv
[ -f /work/scan/DONE_scan ] || exit 0
flag() { aws s3api head-object --bucket "$(echo $1 | cut -d/ -f3)" --key "$(echo $1 | cut -d/ -f4-)" > /dev/null 2>&1; }   # exact key, never a prefix match
if flag $CTL/coord/final || flag $ST/final/READY; then
  INDEX_WORK=/work/index $PY $K/coord/build_index.py --final >> /opt/z3c/index.log 2>&1 && touch /opt/z3c/FINAL_OK
else
  INDEX_WORK=/work/index $PY $K/coord/build_index.py >> /opt/z3c/index.log 2>&1
fi
tail -2 /opt/z3c/index.log | cut -c1-600
aws s3 cp --quiet /opt/z3c/index.log $ST/coord/logs/index.log
[ -f $K/coord/extra_round.sh ] && bash $K/coord/extra_round.sh
true
