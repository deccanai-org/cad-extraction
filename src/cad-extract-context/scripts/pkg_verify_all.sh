#!/bin/bash
# Packaging final VERIFY (read-only pkg.py verify over every project under bim cad-disk-extract/dataset/packages/3d/) - for review.
# Run via: bash /tmp/z3c/ssmcli.sh ap-south-1 i-039e769ea62de0fa1 /tmp/z3c/pkg_verify_all.sh 900
# Idempotent: the first call starts systemd unit z3pkg-verify (the verify can outlast one SSM call); later calls of the same command
# report its progress, then the totals JSON {projects, ok, checks} plus the packager's status.json (projects / files / bytes / STEPs).
#  - pkg.py verify runs WITHOUT PKG_ALLOW_WRITE (read-only on the dataset and the ledger)
#  - the only write: the verify JSON copied to bim cad-disk-extract/_state/packaging/verify_runs/2026-10-02_final.json
#  - no package/active change, no jobs, no deletes
export AWS_DEFAULT_REGION=ap-south-1
PY=/opt/conv/env/bin/python; D=/opt/pkg; O=/opt/pkgverify
mkdir -p $D $O
if [ -f $O/finished ]; then
  echo "verify finished $(cat $O/finished) (started $(cat $O/started))"
  cat $O/verify.json; tail -n 5 $O/verify.log
  echo "== packaging status.json"
  aws s3 cp --quiet s3://bim-proprietary-data/cad-disk-extract/_state/packaging/status.json - | head -c 4000
  exit 0
fi
if systemctl is-active -q z3pkg-verify; then
  echo "verify running since $(cat $O/started)"; tail -n 5 $O/verify.log; exit 0
fi
aws s3 sync --only-show-errors s3://annotationprod/cad-disk-extract/_control/packaging_d3/code/ $D/
grep -m1 -o "pkg-2026-10-02[a-z]" $D/pkgcore.py
systemctl reset-failed z3pkg-verify 2>/dev/null
systemd-run --unit=z3pkg-verify --collect --working-directory=$D --setenv=AWS_DEFAULT_REGION=ap-south-1 /bin/bash -c "
  date -u +%FT%TZ > $O/started
  $PY pkg.py verify --adapter zen3 > $O/verify.json 2> $O/verify.log
  echo rc=\$? >> $O/verify.log
  aws s3 cp --only-show-errors $O/verify.json s3://bim-proprietary-data/cad-disk-extract/_state/packaging/verify_runs/2026-10-02_final.json
  date -u +%FT%TZ > $O/finished"
sleep 5; echo "verify started: $(systemctl is-active z3pkg-verify)"
