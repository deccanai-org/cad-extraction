#!/bin/bash
# READ-ONLY data-4 packaging dry run (lead 01:0xZ 10-04): deployed package kit + the unreleased pkg h files (test/pkgh), in /opt/pkgdr.
# No PKG_ALLOW_WRITE; writes only local /opt/pkgdr. Idempotent: later calls print the report.
export AWS_DEFAULT_REGION=ap-south-1
PY=/opt/conv/env/bin/python; D=/opt/pkgdr
mkdir -p $D
if [ -f $D/finished ]; then echo "finished $(cat $D/finished)"; head -c 6000 $D/report.json; echo; tail -n 3 $D/log.txt; exit 0; fi
if systemctl is-active -q z3pkg-d4dry; then echo running; tail -n 3 $D/log.txt; exit 0; fi
aws s3 sync --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/package/ $D/ --exclude '*/*'
aws s3 sync --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/test/pkgh/ $D/
systemctl reset-failed z3pkg-d4dry 2>/dev/null
systemd-run --unit=z3pkg-d4dry --collect --nice=10 --working-directory=$D --setenv=AWS_DEFAULT_REGION=ap-south-1 /bin/bash -c \
  "$PY pkg.py disk-dryrun --adapter zen4 --plans --out $D/report.json > $D/log.txt 2>&1; echo rc=\$? >> $D/log.txt; date -u +%FT%TZ > $D/finished"
sleep 60; tail -n 5 $D/log.txt
