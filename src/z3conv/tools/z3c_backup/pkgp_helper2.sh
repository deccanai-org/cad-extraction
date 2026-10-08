#!/bin/bash
# upgrade the partial packaging helper on a conversion box: any size, data-3 + data-4, 6 workers, >= 60 GB free per job start
export AWS_DEFAULT_REGION=ap-south-1
D=/opt/pkgphelper; mkdir -p $D/kit $D/work
avail=$(awk '/MemAvailable/{print int($2/1048576)}' /proc/meminfo)
if systemctl is-active -q z3pkgp-helper2; then echo "helper2 running: ok $(grep -c ' ok ' $D/helper2.log) fail $(grep -c ' fail ' $D/helper2.log)"; exit 0; fi
[ "$avail" -lt 120 ] && { echo "skip: only ${avail} GB free"; exit 0; }
touch $D/stop; systemctl stop z3pkgp-helper 2>/dev/null; rm -f $D/stop      # old helper: SIGTERM releases its locks
for f in pkgcore.py pkg.py adapter_zen3.py adapter_zen4.py; do aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/package_partial/kit/$f $D/kit/$f || { echo "kit failed"; exit 1; }; done
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/package_partial/pkgbox_helper.py $D/helper2.py || { echo "helper failed"; exit 1; }
date -u +%FT%TZ > $D/started2
systemctl reset-failed z3pkgp-helper2 2>/dev/null
systemd-run --unit=z3pkgp-helper2 --collect --nice=10 --working-directory=$D/kit --setenv=AWS_DEFAULT_REGION=ap-south-1 --setenv=PKG_TIER=partial \
  --setenv=PKG_ALLOW_WRITE=1 --setenv='PKG_PARTIAL_REQUIRE_CODE={"db1": "z3-db1-2026-10-01v"}' \
  --setenv=PKG_D12MAP=s3://bim-proprietary-data/cad-disk-extract/_state/packaging/pkg-resolver-d4/disk12_sha_map_all.jsonl.gz \
  --setenv=PKGH_PROCS=6 --setenv=PKGH_MAXSZ=1e15 --setenv=PKGH_MINMEM=60 --setenv=PKGH_ADAPTERS=zen3,zen4 \
  /bin/bash -c "/opt/conv/env/bin/python $D/helper2.py >> $D/helper2.log 2>&1; echo rc=\$? >> $D/helper2.log"
sleep 20; echo "helper2: $(systemctl is-active z3pkgp-helper2) mem ${avail}G"; tail -n 1 $D/helper2.log | cut -c1-160
