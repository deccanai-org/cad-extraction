#!/bin/bash
# Packaging canary APPLY - the 3 canary projects in sequence (BOSK "24. IFC", BWXT, SPB_JOB SDS2), each followed by its read-only
# verify; stops at the first nonzero rc or failed verify. For owner/lead review; run only after approval, via:
#   bash /tmp/z3c/ssmcli.sh ap-south-1 i-039e769ea62de0fa1 /tmp/z3c/pkg_canary_apply.sh 900
#  - code: packaging_d3/code/ (pkg-2026-10-02b) synced to /opt/pkg on the coordinator box
#  - job files: packaging_d3/canary/{canary-bosk-24ifc,canary-bwxt,canary-spb-sds2}.json (index_key = live index)
#  - writes (PKG_ALLOW_WRITE=1 on the pkg.py job command only): each project's folder under bim cad-disk-extract/dataset/packages/3d/
#    <project>/ and its _state/packaging/ records (lock, plan, done, ledger part); the packager never deletes
#  - read-only pkg.py verify per project (every check must be 0)
#  - also uploads the dry-run plans /opt/pkgplan/*.plan.json.gz to bim cad-disk-extract/_state/packaging/dryrun/2026-10-02/plans/
#  - no package/active flag, no coordinator hook, no other project
export AWS_DEFAULT_REGION=ap-south-1
PY=/opt/conv/env/bin/python; D=/opt/pkg; W=/opt/pkgwork
mkdir -p $D $W
aws s3 cp --only-show-errors --recursive /opt/pkgplan/ s3://bim-proprietary-data/cad-disk-extract/_state/packaging/dryrun/2026-10-02/plans/ --exclude '*' --include '*.plan.json.gz'
echo "plans uploaded: $(ls /opt/pkgplan/*.plan.json.gz 2>/dev/null | wc -l)"
aws s3 sync --only-show-errors s3://annotationprod/cad-disk-extract/_control/packaging_d3/code/ $D/
grep -m1 -o "pkg-2026-10-02[a-z]" $D/pkgcore.py
for J in canary-bosk-24ifc canary-bwxt canary-spb-sds2; do
  aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/packaging_d3/canary/$J.json $W/$J.json || { echo "STOP: $J job file missing"; exit 1; }
  PJ=$($PY -c "import json; print(json.load(open('$W/$J.json'))['project_id'])")
  echo "== $J: $PJ"
  cd $D && PKG_ALLOW_WRITE=1 timeout 1800 $PY pkg.py job --job $W/$J.json --workdir $W/$J > $W/$J.log 2>&1; rc=$?
  echo "job rc=$rc"; tail -n 12 $W/$J.log
  [ $rc -eq 0 ] || { echo "STOP: $J job rc=$rc"; exit 1; }
  cd $D && timeout 900 $PY pkg.py verify --adapter zen3 --projects "$PJ" > $W/$J.verify.log 2>&1; vrc=$?
  echo "verify rc=$vrc"; tail -n 25 $W/$J.verify.log
  [ $vrc -eq 0 ] || { echo "STOP: $J verify rc=$vrc"; exit 1; }
  grep -q '"ok": 1,' $W/$J.verify.log || { echo "STOP: $J verify checks not all 0"; exit 1; }   # pkg.py verify exits 0 even on failed checks
done
echo "all 3 canary projects applied and verified"
