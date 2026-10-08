#!/bin/bash
# coordinator round (re-downloaded every round): sync the coord kit, run the scan once, then the status/index builder.
export AWS_DEFAULT_REGION=ap-south-1
CTL=s3://annotationprod/cad-disk-extract/_control/z3conv
ST=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/conv
PY=/opt/z3c/venv/bin/python
K=/opt/z3c/kit; mkdir -p $K /work/scan
aws s3 sync --quiet $CTL/coord/ $K/coord/
aws s3 sync --quiet $CTL/scan/ $K/scan/
flag() { aws s3api head-object --bucket "$(echo $1 | cut -d/ -f3)" --key "$(echo $1 | cut -d/ -f4-)" > /dev/null 2>&1; }   # exact key
echo "$(date -u +%FT%TZ) round start"
if [ ! -f /work/scan/DONE_scan ] || flag $CTL/scan/rescan; then
  if flag $CTL/scan/rescan; then rm -f /work/scan/DONE_scan; fi
  SCAN_WORK=/work/scan $PY $K/scan/z3scan.py a b > /work/scan/scan.log 2>&1
  rc=$?
  aws s3 cp --quiet /work/scan/scan.log $ST/scan/scan.log
  echo "$(date -u +%FT%TZ) scan rc=$rc"
  [ $rc -eq 0 ] && touch /work/scan/DONE_scan
fi
if [ -f $K/coord/coord_round.sh ]; then bash $K/coord/coord_round.sh; fi
if { flag $CTL/coord/finish && [ -f /opt/z3c/FINAL_OK ]; } || flag $CTL/coord/release; then touch /opt/z3c/DONE; fi
sleep 60
