#!/bin/bash
# Census of zentitude-data-4 conversion inputs (lead 05:0xZ, owner: run the other disks through the same pipeline).
# READ-ONLY on sources and on data-3 state; writes ONLY bim cad-disk-extract/zentitude-data-4/_state/conv2/scan/ (census.json, parts.tgz).
# No deletes. Run on the coordinator: bash /tmp/z3c/ssmcli.sh ap-south-1 i-039e769ea62de0fa1 /tmp/z3c/zcensus_d4.sh 300
#  - kit: z3conv/scan/zcensus.py from the control prefix (deployed with deploy.sh scan)
#  - one-off transient unit zcensus-d4 at nice 19 (exits when done; not a service); procs = half the box's vCPUs
#  - work dir /opt/zcensus/d4 (manifests are downloaded one at a time per process and deleted after parsing)
#  - idempotent: later calls of the same command print progress, then the census result
export AWS_DEFAULT_REGION=ap-south-1
PY=/opt/conv/env/bin/python; O=/opt/zcensus; K=$O/kit
mkdir -p $O $K
if [ -f $O/finished.d4 ]; then echo "finished $(cat $O/finished.d4)"; tail -n 4 $O/log.d4.txt | cut -c1-8000; exit 0; fi
if systemctl is-active -q zcensus-d4; then echo "running since $(cat $O/started.d4)"; tail -n 4 $O/log.d4.txt; exit 0; fi
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/scan/zcensus.py $K/zcensus.py || exit 1
sha256sum $K/zcensus.py; nproc; free -g | sed -n 2p; df -h /opt | tail -1
date -u +%FT%TZ > $O/started.d4
systemctl reset-failed zcensus-d4 2>/dev/null
systemd-run --unit=zcensus-d4 --collect --nice=19 --setenv=AWS_DEFAULT_REGION=ap-south-1 --setenv=CENSUS_WORK=$O/d4 /bin/bash -c \
  "$PY $K/zcensus.py zentitude-data-4 > $O/log.d4.txt 2>&1; echo rc=\$? >> $O/log.d4.txt; date -u +%FT%TZ > $O/finished.d4"
sleep 90
tail -n 4 $O/log.d4.txt
