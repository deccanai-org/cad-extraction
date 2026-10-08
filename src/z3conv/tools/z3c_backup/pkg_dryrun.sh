#!/bin/bash
# Packaging DRY RUN (lead approval 22:40Z for the cache write; for owner review before any allow rule).
# Runs on the coordinator box i-039e769ea62de0fa1 via: bash /tmp/z3c/ssmcli.sh ap-south-1 i-039e769ea62de0fa1 /tmp/z3c/pkg_dryrun.sh 120
#  - syncs the packager code (packaging_d3/code/, currently pkg-2026-10-02b) to /opt/pkg on the box
#  - ONE systemd unit (z3pkg-dryrun):
#      1. build-d4-index --procs 16: the only write, to bim cad-disk-extract/_state/packaging/cache/d4_index/ (PKG_ALLOW_WRITE=1 set
#         for this command only)
#      2. 16 read-only plan shards (no PKG_ALLOW_WRITE) -> local /opt/pkgplan/
#      3. copies the summaries + logs to bim cad-disk-extract/_state/packaging/dryrun/2026-10-02/
#  - nothing under dataset/packages/; no package/active flag; no coordinator hook; no package jobs
export AWS_DEFAULT_REGION=ap-south-1
PY=/opt/conv/env/bin/python; D=/opt/pkg; O=/opt/pkgplan
mkdir -p $D $O
aws s3 sync --only-show-errors s3://annotationprod/cad-disk-extract/_control/packaging_d3/code/ $D/
grep -m1 -o "pkg-2026-10-02[a-z]" $D/pkgcore.py
systemctl stop z3pkg-dryrun 2>/dev/null; systemctl reset-failed z3pkg-dryrun 2>/dev/null
systemd-run --unit=z3pkg-dryrun --collect --working-directory=$D --setenv=AWS_DEFAULT_REGION=ap-south-1 /bin/bash -c "
  date -u +%FT%TZ > $O/started
  PKG_ALLOW_WRITE=1 $PY pkg.py build-d4-index --procs 16 > $O/d4_index.log 2>&1; echo d4_rc=\$? >> $O/started
  for i in \$(seq 0 15); do $PY pkg.py plan --adapter zen3 --all --gz --shard \$i/16 --out $O > $O/plan_\$i.log 2>&1 & done; wait
  date -u +%FT%TZ > $O/finished
  aws s3 cp --only-show-errors --recursive $O/ s3://bim-proprietary-data/cad-disk-extract/_state/packaging/dryrun/2026-10-02/ --exclude '*' --include 'summary.*' --include '*.log' --include 'started' --include 'finished'"
sleep 20; systemctl is-active z3pkg-dryrun; tail -n 3 $O/d4_index.log 2>/dev/null
